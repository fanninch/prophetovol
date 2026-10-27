"""Run configuration (RUN-1), templates (RUN-2), the step schedule and pre-flight (RUN-10 to RUN-12)."""

from __future__ import annotations

import copy
from datetime import date, datetime, timezone

import pydantic
import pytest

from prophetovol.core.context import CallContext
from prophetovol.core.errors import NotFoundError, ValidationFailed
from prophetovol.core.records import AttemptOutcome, DataVersionRecord, VersionState
from prophetovol.data.lifecycle import DataSelection
from prophetovol.engine.schedule import Step, StepSchedule
from prophetovol.reference.calendar import nyse_calendar
from prophetovol.runs.config import RunConfig
from prophetovol.runs.preflight import PreflightFailed, check_data
from prophetovol.runs.service import BacktestService
from prophetovol.strategy.io import example_specs
from prophetovol.testdata.generator import GeneratorConfig, generate

CTX = CallContext.for_channel("library")
CAL = nyse_calendar()
START, END = date(2024, 3, 18), date(2024, 4, 5)
BASE = {"start_date": START, "end_date": END, "capital": 1_000_000}


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    out = tmp_path_factory.mktemp("preflight-data")
    generate(GeneratorConfig(start_date=START, end_date=END, monthly_count=2, weekly_count=2, dailies=False), out)
    return out


def loaded(tmp_path, files) -> BacktestService:
    svc = BacktestService.open(tmp_path / "home")
    job = svc.import_files([files], CTX)
    svc.commit_import(job.result["import_id"], "replace", CTX)
    for doc in example_specs().values():
        svc.publish_spec(doc, CTX)
    return svc


class TestRunConfig:
    def test_defaults_are_the_requirements(self):
        config = RunConfig(**BASE)
        assert config.model_dump(mode="json", exclude={"start_date", "end_date", "capital"}) == {
            "underlying": None, "data_source": "ivolatility_eod", "frequency": "end_of_day",
            "fill_model": "cross_spread", "fraction": None, "commission_per_contract": 0.0, "hedge_cost_bps": 0.0,
            "rounding": "whole", "stress_mode": "monitor", "stress_discount_rate": 0.0,
            "stale_mark_warning_steps": 5, "allow_missing_days": False, "label": "", "notes": ""}

    def test_stress_mode_documents_every_mode(self):
        text = RunConfig.model_fields["stress_mode"].description
        for words in ("monitor (default)", "scale_to_limit", "q_max", "halt_run", "never gated", "milestone M3"):
            assert words in text

    @pytest.mark.parametrize("change, message", [
        ({"start_date": date(2024, 5, 1)}, "start_date 2024-05-01 is after end_date"),
        ({"fill_model": "mid_plus_fraction"}, "needs a fraction"),
        ({"fraction": 0.5}, "fraction applies only to mid_plus_fraction"),
        ({"stress_mode": "halt_run"}, "arrives with stress in milestone M3"),
        ({"capital": 0}, "greater than 0"),
        ({"rounding": "nearest"}, "whole"),
        ({"spread": 1}, "Extra inputs"),
    ])
    def test_invalid_configurations(self, change, message):
        with pytest.raises(pydantic.ValidationError, match=message):
            RunConfig(**(BASE | change))

    def test_hash_ignores_key_order_and_follows_content(self):
        a = RunConfig.model_validate(BASE | {"label": "x"})
        b = RunConfig.model_validate(dict(reversed(list((BASE | {"label": "x"}).items()))))
        assert a.config_hash() == b.config_hash() != RunConfig(**BASE).config_hash()

    def test_resolution_and_fill_model_params(self):
        assert RunConfig(**BASE).resolved("SPX").underlying == "SPX"
        with pytest.raises(ValueError, match="differs from the spec's SPX"):
            RunConfig(**BASE, underlying="NDX").resolved("SPX")
        params = RunConfig(**BASE, fill_model="mid_plus_fraction", fraction=0.25).fill_model_params()
        assert params.fill_model == "mid_plus_fraction" and params.fraction == 0.25
        assert RunConfig(**BASE).fill_model_params().fill_model == "cross_spread"


class TestTemplates:
    def test_versions_and_unchanged_content(self, tmp_path):
        body = {"name": "standard", "description": "Cross the spread, $1 commission.",
                "config": BASE | {"commission_per_contract": 1.0}}
        with BacktestService.open(tmp_path / "home") as svc:
            first, created = svc.save_run_template(copy.deepcopy(body), CTX)
            assert created and first.version == 1
            assert not svc.save_run_template(copy.deepcopy(body), CTX)[1]
            body["config"]["rounding"] = "fractional"
            second, created = svc.save_run_template(body, CTX)
            assert created and second.version == 2
            assert svc.get_run_template("standard", 1).config.rounding == "whole"
            assert svc.get_run_template("standard").config.rounding == "fractional"
            assert [d.key for d in svc.list_run_templates()] == ["standard"]
            with pytest.raises(ValidationFailed, match="config.capital"):
                svc.save_run_template({"name": "bad", "config": BASE | {"capital": -1}}, CTX)
            assert svc.page_attempts().items[0].outcome == AttemptOutcome.REJECTED


class TestSchedule:
    def test_lookups(self):
        t = datetime(2024, 1, 1, tzinfo=timezone.utc)
        schedule = StepSchedule(steps=[Step(seq=1, day=date(2024, 5, 8), as_of=t),
                                       Step(seq=2, day=date(2024, 5, 10), as_of=t, after_missing_days=[date(2024, 5, 9)])],
                                missing_days=[date(2024, 5, 9)])
        assert schedule.has_step(date(2024, 5, 10)) and not schedule.has_step(date(2024, 5, 9))
        assert schedule.step_on(date(2024, 5, 10)).seq == 2 and schedule.step_on(date(2024, 5, 11)) is None
        assert schedule.last_step_before(date(2024, 5, 9)).seq == 1
        assert schedule.last_step_before(date(2024, 5, 10)).seq == 1
        assert schedule.last_step_before(date(2024, 5, 8)) is None
        assert schedule.is_missing(date(2024, 5, 9)) and not schedule.is_missing(date(2024, 5, 8))


def versions(days, import_id="imp_a", contracts=10):
    return [DataVersionRecord(underlying="SPX", as_of=datetime(d.year, d.month, d.day, 20, 15, tzinfo=timezone.utc),
                              as_of_date=d, import_id=import_id, state=VersionState.ACTIVE, contracts=contracts,
                              state_changed_at=datetime(2024, 1, 1, tzinfo=timezone.utc)) for d in days]


class TestCheckData:
    CONFIG = RunConfig(underlying="SPX", start_date=date(2024, 5, 6), end_date=date(2024, 5, 10), capital=1e6)

    def test_every_problem_at_once(self):
        active = (versions([date(2024, 5, 6), date(2024, 5, 7)]) + versions([date(2024, 5, 8)], contracts=0)
                  + versions([date(2024, 5, 11)]) + versions([date(2024, 5, 10)], import_id="imp_b"))
        schedule, used, errors, warnings = check_data(self.CONFIG, CAL, active, {"imp_a": "ivolatility_eod",
                                                                                  "imp_b": "other_vendor"})
        assert schedule is None and used == []
        messages = [e.message for e in errors]
        assert any("import imp_b comes from data source other_vendor" in m for m in messages)
        assert any("1 snapshot(s) have no contracts: 2024-05-08" in m for m in messages)
        assert any("1 trading day(s) have no active snapshot for SPX: 2024-05-09" in m and "allow_missing_days" in m
                   for m in messages)
        assert [w.message for w in warnings] == []  # 2024-05-11 is out of range: ignored silently

    def test_non_trading_dates_and_long_lists(self):
        active = versions([date(2024, 5, d) for d in (6, 7, 8, 9, 10)] + [date(2024, 5, 11)])
        config = self.CONFIG.model_copy(update={"end_date": date(2024, 5, 12)})
        schedule, used, errors, warnings = check_data(config, CAL, active, {"imp_a": "ivolatility_eod"})
        assert not errors and len(schedule.steps) == 5
        assert warnings[0].message == "1 non-trading date(s) have active data and are ignored: 2024-05-11"

    def test_ranges_without_trading_days(self):
        weekend = self.CONFIG.model_copy(update={"start_date": date(2024, 5, 11), "end_date": date(2024, 5, 12)})
        assert check_data(weekend, CAL, [], {})[2][0].message == "no trading day between 2024-05-11 and 2024-05-12"
        ancient = self.CONFIG.model_copy(update={"start_date": date(1980, 1, 2)})
        assert "outside the trading calendar's range" in check_data(ancient, CAL, [], {})[2][0].message


class TestPreflight:
    def test_a_complete_range_passes(self, tmp_path, files):
        with loaded(tmp_path, files) as svc:
            report = svc.preflight_run("put_diagonal_banded", BASE, CTX)
            sessions = CAL.sessions_in_range(START, END)
            assert report.ok and [s.day for s in report.schedule.steps] == sessions
            assert [s.seq for s in report.schedule.steps] == list(range(1, len(sessions) + 1))
            assert [v.as_of for v in report.data_versions] == [s.as_of for s in report.schedule.steps]
            assert report.config.underlying == "SPX" and report.config_hash == report.config.config_hash()
            spec = svc.get_spec_version("put_diagonal_banded")
            assert (report.spec_version, report.spec_hash) == (spec.version, spec.content_hash)
            assert svc.page_attempts().items[0].operation == "run.preflight"

    def test_missing_days_block_then_are_skipped(self, tmp_path, files):
        with loaded(tmp_path, files) as svc:
            gap = date(2024, 3, 27)
            svc.delete_data(svc.preview_data_change("delete", DataSelection(underlying="SPX", start=gap, end=gap), CTX),
                            CTX, confirmed=True)
            with pytest.raises(PreflightFailed) as caught:
                svc.preflight_run("put_diagonal_banded", BASE, CTX)
            assert caught.value.report.errors[0].message.startswith("1 trading day(s) have no active snapshot for SPX: "
                                                                     "2024-03-27")
            assert caught.value.report.schedule is None
            assert svc.page_attempts().items[0].outcome == AttemptOutcome.REJECTED
            report = svc.preflight_run("put_diagonal_banded", BASE | {"allow_missing_days": True}, CTX)
            schedule = report.schedule
            assert not schedule.has_step(gap) and schedule.missing_days == [gap]
            assert schedule.step_on(date(2024, 3, 28)).after_missing_days == [gap]
            assert schedule.last_step_before(gap).day == date(2024, 3, 26)
            assert [w.message for w in report.warnings] == [
                "skipping 1 trading day(s) without data: 2024-03-27; the next step after each is flagged "
                "missing_day_before.",
                "2024-03-27 is skipped: PM-settled contracts settling on it are closed at the step before (SPEC-55)."]

    def test_configuration_problems_are_reported_together(self, tmp_path, files):
        with loaded(tmp_path, files) as svc:
            with pytest.raises(PreflightFailed) as caught:
                svc.preflight_run("short_call_hedged", BASE | {"capital": -5, "stale_mark_warning_steps": 0}, CTX)
            assert [e.path for e in caught.value.report.errors] == ["config.capital", "config.stale_mark_warning_steps"]
            with pytest.raises(PreflightFailed) as caught:
                svc.preflight_run("short_call_hedged", BASE | {"underlying": "NDX"}, CTX)
            assert caught.value.report.errors[0].path == "config.underlying"
            with pytest.raises(PreflightFailed) as caught:
                svc.preflight_run("short_call_hedged", BASE | {"data_source": "nope"}, CTX)
            assert caught.value.report.errors[0].message.startswith("unknown data source 'nope'")

    def test_spec_findings_are_included(self, tmp_path, files):
        with loaded(tmp_path, files) as svc:
            doc = example_specs()["short_call_hedged"]
            doc["triggers"][0]["any_of"] = doc["triggers"][0]["any_of"][:2]
            svc.publish_spec(doc, CTX)
            report = svc.preflight_run("short_call_hedged", BASE, CTX)
            assert report.ok and report.spec_version == 2
            assert report.warnings[0].path == "spec.legs[0]" and "force-close" in report.warnings[0].message
            with pytest.raises(NotFoundError, match="no strategy_spec named 'nope'"):
                svc.preflight_run("nope", BASE, CTX)
            assert svc.preflight_run("short_call_hedged", BASE, CTX, spec_version=1).warnings == []
