"""Market data for runs: the provider, the horizon, and the point-in-time view (ARC-3, TEST-4, NFR-1)."""

from __future__ import annotations

import re
import time
from datetime import date, timedelta

import pyarrow as pa
import pytest

from prophetovol.core.context import CallContext
from prophetovol.core.errors import ConfigurationError, PointInTimeError
from prophetovol.engine.view import ENGINE_COLUMNS, MarketDataView
from prophetovol.runs.provider import MarketDataProvider, spec_horizon_days
from prophetovol.runs.service import BacktestService
from prophetovol.storage.adapter import StorageAdapter
from prophetovol.strategy.io import example_specs
from prophetovol.strategy.model import StrategySpec
from prophetovol.testdata.generator import GeneratorConfig, generate

CTX = CallContext.for_channel("library")
START, END = date(2023, 12, 13), date(2024, 3, 8)  # crosses a year end and three-month chunk boundaries
CONFIG = {"start_date": START, "end_date": END, "capital": 1_000_000}
EXAMPLES = {k: StrategySpec.model_validate(v) for k, v in example_specs().items()}
SORT = [("root", "ascending"), ("expiration", "ascending"), ("option_type", "ascending"), ("strike", "ascending")]


@pytest.fixture(scope="module")
def home(tmp_path_factory):
    folder = tmp_path_factory.mktemp("market-data")
    generate(GeneratorConfig(start_date=START, end_date=END, monthly_count=3, weekly_count=2), folder / "files")
    with BacktestService.open(folder / "home") as svc:
        job = svc.import_files([folder / "files"], CTX)
        svc.commit_import(job.result["import_id"], "replace", CTX)
        for doc in example_specs().values():
            svc.publish_spec(doc, CTX)
    return folder


def spec_with(expiration: dict) -> StrategySpec:
    doc = example_specs()["short_call_hedged"]
    doc["legs"][0]["expiration"] = expiration
    return StrategySpec.model_validate(doc)


class TestHorizon:
    def test_examples(self):
        assert spec_horizon_days(EXAMPLES["short_call_hedged"]) == 55  # 45 days, max_days 55
        assert spec_horizon_days(EXAMPLES["long_butterfly_60d"]) == 70  # same_as_leg follows the 60-day leg
        assert spec_horizon_days(EXAMPLES["put_diagonal_banded"]) == 85

    def test_trading_days_and_unbounded_selectors(self):
        assert spec_horizon_days(spec_with({"selector": "trading_days_out", "n": 1})) == 12
        assert spec_horizon_days(spec_with({"selector": "trading_days_out", "n": 5, "tolerance": 2})) == 19
        assert spec_horizon_days(spec_with({"selector": "target_days", "days": 0.5, "max_days": 1})) == 1
        assert spec_horizon_days(spec_with({"selector": "nth_expiration", "n": 2})) is None


class TestProvider:
    def test_views_match_direct_snapshot_reads(self, home):
        with BacktestService.open(home / "home") as svc:
            report = svc.preflight_run("put_diagonal_banded", CONFIG, CTX)
            provider = svc.market_data(report, svc.get_spec("put_diagonal_banded"))
            views = list(provider.views())
            assert [v.step for v in views] == [s.seq for s in report.schedule.steps]
            assert [v.as_of_date for v in views] == [s.day for s in report.schedule.steps]
            assert provider.stats.chunks == 2  # Dec–Feb, then March
            for view in views[::9] + [views[-1]]:
                direct = svc.storage.read_active_snapshot("SPX", view.as_of, list(ENGINE_COLUMNS))
                direct = direct.filter(pa.compute.less_equal(direct.column("days_to_expiry"), 85)).sort_by(SORT)
                assert view.table().to_pylist() == direct.to_pylist()
                level = svc.storage.read_active_snapshot("SPX", view.as_of, ["index_level"]).column("index_level")
                assert view.index_level == level[0].as_py()
                assert view.table().column_names == list(ENGINE_COLUMNS)

    def test_horizon_limits_rows_and_none_reads_everything(self, home):
        with BacktestService.open(home / "home") as svc:
            report = svc.preflight_run("short_call_hedged", CONFIG, CTX)
            near = MarketDataProvider(svc.storage, "SPX", report.schedule, report.data_versions, horizon_days=55)
            every = MarketDataProvider(svc.storage, "SPX", report.schedule, report.data_versions, horizon_days=None)
            for a, b in zip(near.views(), every.views()):
                assert max(a.column("days_to_expiry")) <= 55 < max(b.column("days_to_expiry"))
                assert len(a) < len(b) and a.index_level == b.index_level

    def test_a_step_with_no_rows_in_the_horizon_still_has_its_index_level(self, home):
        with BacktestService.open(home / "home") as svc:
            report = svc.preflight_run("short_call_hedged", CONFIG, CTX)
            provider = MarketDataProvider(svc.storage, "SPX", report.schedule, report.data_versions, horizon_days=-1)
            view = next(provider.views())
            assert len(view) == 0 and view.expirations() == [] and view.index_level > 0

    def test_runs_read_the_versions_captured_at_preflight(self, home, tmp_path):
        with BacktestService.open(home / "home") as svc:
            report = svc.preflight_run("short_call_hedged", CONFIG, CTX)
            captured = {v.import_id for v in report.data_versions}
            job = svc.import_files([home / "files"], CTX)
            svc.commit_import(job.result["import_id"], "replace", CTX)  # every day now has a newer active version
            provider = MarketDataProvider(svc.storage, "SPX", report.schedule, report.data_versions,
                                          columns=(*ENGINE_COLUMNS, "import_id"))
            read = {i for view in provider.views() for i in view.column("import_id")}
            assert read == captured != {job.result["import_id"]}
            fresh = svc.preflight_run("short_call_hedged", CONFIG, CTX)
            assert {v.import_id for v in fresh.data_versions} == {job.result["import_id"]}

    def test_mismatched_schedule_and_versions_are_refused(self, home):
        with BacktestService.open(home / "home") as svc:
            report = svc.preflight_run("short_call_hedged", CONFIG, CTX)
            with pytest.raises(ConfigurationError, match="steps but"):
                MarketDataProvider(svc.storage, "SPX", report.schedule, report.data_versions[1:])
            with pytest.raises(ConfigurationError, match="step 1 is as of"):
                MarketDataProvider(svc.storage, "SPX", report.schedule, report.data_versions[1:] + report.data_versions[:1])

    def test_per_step_access_time(self, home):
        with BacktestService.open(home / "home") as svc:
            report = svc.preflight_run("put_diagonal_banded", CONFIG, CTX)
            provider = svc.market_data(report, svc.get_spec("put_diagonal_banded"))
            started = time.perf_counter()
            steps = sum(1 for view in provider.views() if view.expirations() is not None)
            per_step = (time.perf_counter() - started) / steps
            print(f"\nper-step market data access: {per_step * 1000:.2f} ms over {steps} steps "
                  f"({provider.stats.rows:,} rows, {provider.stats.read_seconds:.2f} s reading)")
            assert per_step < 0.25  # recorded, not a tight target: the 10-year run is measured in Phase 15


class TestPointInTime:
    @pytest.fixture
    def view(self, home):
        with BacktestService.open(home / "home") as svc:
            report = svc.preflight_run("put_diagonal_banded", CONFIG, CTX)
            return next(svc.market_data(report, svc.get_spec("put_diagonal_banded")).views())

    def test_every_method_refuses_a_later_as_of(self, view):
        later = view.as_of + timedelta(microseconds=1)
        symbol = view.column("osi_symbol")[0]
        calls = [lambda t: view.table(t), lambda t: view.column("bid", t), lambda t: view.contract(symbol, t),
                 lambda t: view.expirations(t)]
        for call in calls:
            with pytest.raises(PointInTimeError, match=re.escape(f"step 1 is as of {view.as_of.isoformat()}")):
                call(later)
            call(view.as_of)
            call(view.as_of - timedelta(days=1))
            with pytest.raises(ValueError, match="timezone-aware"):
                call(later.replace(tzinfo=None))

    def test_view_contents(self, view):
        symbol = view.column("osi_symbol")[3]
        row = view.contract(symbol)
        assert row["osi_symbol"] == symbol and view.contract("NOT A SYMBOL") is None
        expirations = view.expirations()
        assert sum(e.contracts for e in expirations) == len(view)
        assert [e.expiry_timestamp for e in expirations] == sorted(e.expiry_timestamp for e in expirations)
        assert {e.root for e in expirations} == {"SPX", "SPXW"}
        # contracts expiring today are still listed on their settlement date; SPEC-15 excludes them from selection
        assert all(e.expiry_timestamp > view.as_of or e.settlement_date == view.as_of_date for e in expirations)

    def test_the_engine_gets_views_and_never_the_provider_or_storage(self, view):
        held = [getattr(view, slot) for slot in MarketDataView.__slots__]
        assert not any(isinstance(v, (MarketDataProvider, StorageAdapter, BacktestService)) for v in held)
        assert not hasattr(view, "__dict__")  # nothing can be attached to it later
        with pytest.raises(AttributeError):
            view.as_of = view.as_of
