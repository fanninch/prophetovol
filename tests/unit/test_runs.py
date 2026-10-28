"""Runs end to end through the service: lifecycle, provenance, results and failures (RUN-20 to RUN-40)."""

from __future__ import annotations

from datetime import date

import pytest

import prophetovol.engine.loop as loop
import prophetovol.runs.coordinator as coordinator
from prophetovol.core.context import CallContext
from prophetovol.core.errors import ValidationFailed
from prophetovol.core.ids import content_hash
from prophetovol.core.records import AttemptOutcome, JobStatus, RunStatus
from prophetovol.engine.invariants import InvariantViolation
from prophetovol.runs.config import RunConfig
from prophetovol.runs.preflight import PreflightFailed
from prophetovol.runs.provider import MarketDataProvider
from prophetovol.runs.service import BacktestService
from prophetovol.storage.duckdb.adapter import DuckDBAdapter
from prophetovol.strategy.io import example_specs
from prophetovol.testdata.generator import GeneratorConfig, generate

CTX = CallContext.for_channel("library")
CONFIG = {"start_date": date(2024, 4, 1), "end_date": date(2024, 4, 30), "capital": 1_000_000, "label": "test"}
SPEC = "put_diagonal_banded"


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    out = tmp_path_factory.mktemp("run-data")
    generate(GeneratorConfig(start_date=date(2024, 3, 1), end_date=date(2024, 4, 30)), out)
    return out


@pytest.fixture
def svc(tmp_path, files):
    service = BacktestService.open(tmp_path / "home")
    job = service.import_files([files], CTX)
    service.commit_import(job.result["import_id"], "replace", CTX)
    for doc in example_specs().values():
        service.publish_spec(doc, CTX)
    yield service
    service.close()


def counts(svc, run_id):
    return {t: svc.storage.count_run_results(run_id, t)
            for t in ("position_snapshots", "portfolio_snapshots", "trades", "structures", "events")}


def stop_after(steps, monkeypatch, how):
    """Make the market data provider stop after a number of steps: Ctrl+C, or a cancellation request."""
    original = MarketDataProvider.views

    def views(self):
        for i, view in enumerate(original(self)):
            if i == steps:
                if how == "interrupt":
                    raise KeyboardInterrupt()
            yield view

    monkeypatch.setattr(MarketDataProvider, "views", views)


class TestCompletedRun:
    def test_provenance_and_results(self, svc):
        progress = []
        run = svc.start_run(SPEC, CONFIG, CTX, on_progress=lambda d, t, a: progress.append((d, t)))
        assert run.status == RunStatus.COMPLETED and run.steps_completed == run.steps_total == 22
        assert progress[-1] == (22, 22) and len(progress) == 22
        spec = svc.get_spec_version(SPEC)
        assert (run.spec_id, run.spec_version, run.spec_hash) == (SPEC, spec.version, spec.content_hash)
        assert run.config_hash == content_hash(run.config) == RunConfig.model_validate(run.config).config_hash()
        assert run.config["underlying"] == "SPX" and run.label == "test"
        assert run.registry_versions == {
            "constructor/rules": "1", "entry_schedule/when_flat": "1", "expiration_selector/target_days": "1",
            "fill_model/cross_spread": "1", "hedge_rule/band": "1", "settlement_source/pm_index_close": "1",
            "sizing_method/contracts": "1", "strike_selector/delta": "1", "trigger_action/roll": "1",
            "trigger_condition/leg_days_to_expiry_at_or_below": "1"}
        assert run.software_versions["prophetovol"] and run.calendar_version == svc.calendar.version
        assert (run.underlying_version, run.data_source_version) == (1, 1)
        assert len(svc.storage.run_data_versions(run.run_id)) == 22
        assert run.started_at <= run.finished_at and run.actor == CTX.actor and run.channel == CTX.channel
        job = svc.get_job(run.job_id)
        assert job.status == JobStatus.SUCCEEDED and job.result == {"run_id": run.run_id, "status": "completed"}
        assert (job.progress_done, job.progress_total) == (22, 22)
        stored = counts(svc, run.run_id)
        assert stored["portfolio_snapshots"] == 22 and stored["structures"] >= 1 and stored["trades"] >= 2
        last = svc.run_results(run.run_id, "portfolio_snapshots").to_pylist()[-1]
        assert (run.final_pnl, run.final_equity) == (pytest.approx(last["cumulative_pnl"]), pytest.approx(last["equity"]))
        assert [a.operation for a in svc.page_attempts(limit=3).items][:2] == ["run.start", "run.preflight"]

    def test_same_inputs_give_the_same_stored_results(self, svc):
        a, b = svc.start_run(SPEC, CONFIG, CTX), svc.start_run(SPEC, CONFIG, CTX)
        for table in ("position_snapshots", "portfolio_snapshots", "trades", "structures", "events"):
            rows = [svc.run_results(r.run_id, table).drop(["run_id"]).to_pylist() for r in (a, b)]
            assert rows[0] == rows[1], table

    def test_structure_snapshots_agree_with_structures(self, svc):
        run = svc.start_run(SPEC, CONFIG, CTX)
        view = svc.run_results(run.run_id, "structure_snapshots").to_pylist()
        for s in svc.run_results(run.run_id, "structures").to_pylist():
            last = [v for v in view if v["structure_id"] == s["structure_id"]][-1]
            assert last["cumulative_pnl"] == pytest.approx(s["cumulative_pnl"])

    def test_background_run_with_a_reader_listing_runs(self, svc):
        svc.start_jobs(svc.job_handlers())
        try:
            run = svc.start_run(SPEC, CONFIG, CTX, background=True)
            assert run.status == RunStatus.QUEUED and run.job_id
            reader = svc.reader()
            assert reader.page_runs().total == 1  # readers work while the job runs
            assert svc.jobs.wait(run.job_id, timeout=120)
        finally:
            svc.stop_jobs()
        assert svc.get_run(run.run_id).status == RunStatus.COMPLETED
        with pytest.raises(ValidationFailed, match="only queued or running runs can be cancelled"):
            svc.cancel_run(run.run_id, CTX)


class TestStoppedRuns:
    def test_preflight_failure_records_nothing(self, svc):
        with pytest.raises(PreflightFailed):
            svc.start_run(SPEC, CONFIG | {"end_date": date(2024, 5, 31)}, CTX)  # May has no data
        assert svc.page_runs().total == 0
        assert svc.page_attempts().items[0].outcome == AttemptOutcome.REJECTED

    def test_ctrl_c_keeps_the_finished_steps(self, svc, monkeypatch):
        stop_after(5, monkeypatch, "interrupt")
        run = svc.start_run(SPEC, CONFIG, CTX)
        assert (run.status, run.steps_completed, run.error) == (RunStatus.CANCELLED, 5, "cancelled by the user")
        assert counts(svc, run.run_id)["portfolio_snapshots"] == 5
        assert svc.get_job(run.job_id).status == JobStatus.CANCELLED
        assert run.final_pnl is not None

    def test_cancellation_at_a_step_boundary(self, svc, monkeypatch):
        original = loop.run_engine

        def cancel_after_three(*args, **kwargs):
            progress = kwargs["progress"]
            seen = []
            kwargs["progress"] = lambda d, t, a: (seen.append(d), progress(d, t, a))
            kwargs["cancelled"] = lambda: len(seen) >= 3
            return original(*args, **kwargs)

        monkeypatch.setattr(coordinator, "run_engine", cancel_after_three)
        run = svc.start_run(SPEC, CONFIG, CTX)
        assert (run.status, run.steps_completed) == (RunStatus.CANCELLED, 3)
        assert counts(svc, run.run_id)["portfolio_snapshots"] == 3

    def test_engine_failure_stores_partial_results(self, svc, monkeypatch):
        def violation(recorder):
            raise InvariantViolation("step 22: injected")

        monkeypatch.setattr(loop, "check_invariants", violation)
        run = svc.start_run(SPEC, CONFIG, CTX)
        assert (run.status, run.partial, run.error) == (RunStatus.FAILED, True, "step 22: injected")
        assert counts(svc, run.run_id)["portfolio_snapshots"] == 22
        job = svc.get_job(run.job_id)
        assert job.status == JobStatus.FAILED and job.result["error_kind"] == "expected"

    def test_failed_write_stores_nothing(self, svc, monkeypatch):
        def broken(self, run_id, tables):
            raise OSError("disk full")

        monkeypatch.setattr(DuckDBAdapter, "write_run_results", broken)
        run = svc.start_run(SPEC, CONFIG, CTX)
        assert (run.status, run.partial) == (RunStatus.FAILED, False)
        assert run.error == "results could not be stored: disk full" and run.final_pnl is None
        assert all(n == 0 for n in counts(svc, run.run_id).values())
        assert svc.get_job(run.job_id).result["error_kind"] == "unexpected"

    def test_interrupted_runs_are_failed_on_open(self, svc, tmp_path):
        run = svc.start_run(SPEC, CONFIG, CTX)
        svc.storage.update_run(run.model_copy(update={"status": RunStatus.RUNNING, "finished_at": None}))
        svc.close()
        with BacktestService.open(tmp_path / "home") as again:
            assert again.recovered_runs == [run.run_id]
            recovered = again.get_run(run.run_id)
            assert recovered.status == RunStatus.FAILED and recovered.error.startswith("interrupted")


class TestDataSuperseded:
    def test_replacing_data_a_run_read_flags_it(self, svc, files):
        run = svc.start_run(SPEC, CONFIG, CTX)
        assert not run.data_superseded
        job = svc.import_files([files], CTX)
        svc.commit_import(job.result["import_id"], "replace", CTX)
        flagged = svc.get_run(run.run_id)
        assert flagged.data_superseded
        impacts = svc.run_data_impacts(run.run_id)
        assert impacts[0].underlying == "SPX" and impacts[0].dates[0] == date(2024, 4, 1)
