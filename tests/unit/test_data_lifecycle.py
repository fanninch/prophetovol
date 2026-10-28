"""Phase 7 integration, invalidation, failure atomicity and crash recovery."""

from datetime import date
import shutil
import threading

import duckdb
import pytest
from pydantic import ValidationError

from prophetovol.core.context import CallContext
from prophetovol.core.errors import ValidationFailed
from prophetovol.core.records import JobStatus, VersionState
from prophetovol.data.lifecycle import DataSelection
from prophetovol.runs.jobs import JobCancelled
from prophetovol.runs.service import BacktestService
from prophetovol.storage.duckdb.adapter import DuckDBAdapter
from prophetovol.storage.duckdb.schema import CATALOG_MIGRATIONS, apply_migrations
from tests.contract.test_lifecycle_contract import D1, D2, D3, stage, selection, states
from tests.contract.test_adapter_contract import version

CTX = CallContext.for_channel("library")


@pytest.fixture
def svc(tmp_path):
    with BacktestService.open(tmp_path / "home") as service:
        yield service


def seed_run(adapter, run_id, import_id, days=(D1, D2)):
    adapter._cat.execute("INSERT INTO runs (run_id, status) VALUES (?, 'completed')", [run_id])
    for d in days:
        v = version(import_id, d)
        adapter._cat.execute("INSERT INTO run_data_versions VALUES (?, ?, ?, ?)",
                             [run_id, v.underlying, v.as_of.replace(tzinfo=None), import_id])


def test_invalidation_tracks_exact_versions_and_keeps_runs(svc):
    a = svc.storage
    stage(a, "old")
    a.commit_import("old", "replace")
    seed_run(a, "run_old", "old")
    seed_run(a, "unrelated", "other")
    stage(a, "new", (D2, D3))
    job = svc.commit_import("new", "replace", CTX)
    assert job.status == JobStatus.SUCCEEDED
    impacts = svc.run_data_impacts("run_old")
    assert len(impacts) == 1 and impacts[0].dates == [D2]
    assert svc.run_data_impacts("unrelated") == []
    preview = svc.preview_data_change("delete", selection(D1, D1), CTX)
    assert preview.runs[0].run_id == "run_old"
    assert svc.delete_data(preview, CTX, confirmed=True).status == JobStatus.SUCCEEDED
    assert svc.run_data_impacts("run_old")[0].dates == [D1, D2]
    preview = svc.preview_data_change("purge", DataSelection(import_id="old"), CTX)
    assert svc.purge_data(preview, CTX, confirmed=True).status == JobStatus.SUCCEEDED
    assert svc.run_data_impacts("run_old")[0].dates == [D1, D2]
    assert a._cat.execute("SELECT run_id, data_superseded FROM runs ORDER BY run_id").fetchall() == [
        ("run_old", True), ("unrelated", False)]


@pytest.mark.parametrize("operation", ["delete", "purge"])
def test_confirmation_required_and_audited_even_without_affected_runs(svc, operation):
    stage(svc.storage, "old")
    svc.storage.commit_import("old", "replace")
    preview = svc.preview_data_change(operation, selection(), CTX)
    method = svc.delete_data if operation == "delete" else svc.purge_data
    with pytest.raises(ValidationFailed, match="confirm"):
        method(preview, CTX)
    attempt = svc.page_attempts(operation="data."+operation).items[0]
    assert attempt.outcome == "rejected"
    assert states(svc.storage)["old", D1] == VersionState.ACTIVE


def test_new_dependent_run_invalidates_confirmation(svc):
    a = svc.storage
    stage(a, "old")
    a.commit_import("old", "replace")
    preview = svc.preview_data_change("delete", selection(), CTX)
    seed_run(a, "late", "old")
    with pytest.raises(ValidationFailed, match="changed"):
        svc.delete_data(preview, CTX, confirmed=True)
    with pytest.raises(ValidationFailed, match="changed"):
        a.apply_change(preview)


def test_queued_delete_rechecks_confirmation_at_execution(svc):
    a = svc.storage
    stage(a, "old")
    a.commit_import("old", "replace")
    entered, release = threading.Event(), threading.Event()
    def block(ctx):
        entered.set()
        assert release.wait(10)
    handlers = svc.job_handlers() | {"block": block}
    svc.start_jobs(handlers)
    svc.submit_job("block", {}, CTX)
    assert entered.wait(5)
    preview = svc.preview_data_change("delete", selection(), CTX)
    job = svc.delete_data(preview, CTX, confirmed=True, background=True)
    seed_run(a, "late", "old")
    release.set()
    assert svc.jobs.wait(job.job_id, 10)
    assert svc.get_job(job.job_id).status == JobStatus.FAILED
    assert "changed" in svc.get_job(job.job_id).error
    assert svc.page_attempts(operation="data.execute").items[0].outcome == "rejected"
    assert states(a)["old", D1] == VersionState.ACTIVE


def test_background_commit_and_purge(svc):
    stage(svc.storage, "old")
    svc.start_jobs(svc.job_handlers())
    job = svc.commit_import("old", "replace", CTX, background=True)
    assert svc.jobs.wait(job.job_id, 10)
    assert svc.get_job(job.job_id).result["activated"] == 2
    preview = svc.preview_data_change("delete", selection(), CTX)
    job = svc.delete_data(preview, CTX, confirmed=True, background=True)
    assert svc.jobs.wait(job.job_id, 10)
    preview = svc.preview_data_change("purge", selection(), CTX)
    job = svc.purge_data(preview, CTX, confirmed=True, background=True)
    assert svc.jobs.wait(job.job_id, 10)
    assert svc.get_job(job.job_id).status == JobStatus.SUCCEEDED
    assert svc.get_job(job.job_id).progress_label == "complete"


def test_commit_failure_rolls_back_activation_import_and_invalidation(svc, monkeypatch):
    a = svc.storage
    stage(a, "old")
    a.commit_import("old", "replace")
    seed_run(a, "run", "old")
    stage(a, "new")
    before = states(a)
    original = a._write
    def fail(sql, params):
        if sql.startswith("UPDATE imports SET status"):
            raise RuntimeError("injected")
        return original(sql, params)
    monkeypatch.setattr(a, "_write", fail)
    job = svc.commit_import("new", "replace", CTX)
    assert job.status == JobStatus.FAILED and "injected" in job.error
    assert states(a) == before
    assert svc.run_data_impacts("run") == []
    assert a.get_import("new").status == "staged"
    assert svc.page_attempts(operation="data.execute").items[0].outcome == "error"


@pytest.mark.parametrize("failure", ["exception", "cancel"])
def test_partial_purge_failure_restores_files_and_catalog(svc, failure):
    a = svc.storage
    stage(a, "old", (D1, D2, date(2024, 2, 1)))
    a.commit_import("old", "replace")
    a.apply_change(a.preview_change("delete", selection(D2, date(2024, 2, 1))))
    preview = a.preview_change("purge", DataSelection(import_id="old"))
    before = {p: p.read_bytes() for p in (a.home / "market").rglob("*.parquet")}
    def progress(done, total):
        if done == 3:  # first of two files already replaced
            raise JobCancelled() if failure == "cancel" else RuntimeError("injected")
    with pytest.raises(JobCancelled if failure == "cancel" else RuntimeError):
        a.apply_change(preview, progress=progress)
    assert {p: p.read_bytes() for p in before} == before
    assert a.preview_change("purge", DataSelection(import_id="old")).token == preview.token
    assert not list((a.home / "uploads").glob("files_*"))


@pytest.mark.parametrize("committed", [False, True])
def test_reopen_recovers_file_journal(tmp_path, monkeypatch, committed):
    home = tmp_path / "home"
    a = DuckDBAdapter.open(home)
    stage(a, "old")
    a.commit_import("old", "replace")
    a.apply_change(a.preview_change("delete", selection(D2, D2)))
    preview = a.preview_change("purge", selection())
    if committed:
        original = shutil.rmtree
        def retain(path, *args, **kwargs):
            if path.name.startswith("files_"):
                return
            return original(path, *args, **kwargs)
        monkeypatch.setattr(shutil, "rmtree", retain)
        a.apply_change(preview)
    else:
        def crash_state(*args):
            raise SystemExit("simulated process termination")
        monkeypatch.setattr(a, "_set_state", crash_state)
        with pytest.raises(SystemExit):
            a.apply_change(preview)
    assert list((home / "uploads").glob("files_*"))
    a.close()  # uncommitted DuckDB transaction rolls back
    monkeypatch.undo()
    with_adapter = DuckDBAdapter.open(home)
    try:
        assert with_adapter.read_import_snapshot("old", D1).num_rows == 3
        assert with_adapter.read_import_snapshot("old", D2).num_rows == (0 if committed else 3)
        assert states(with_adapter)["old", D2] == (VersionState.PURGED if committed else VersionState.DELETED)
        assert not list((home / "uploads").glob("files_*"))
    finally:
        with_adapter.close()


def test_v1_home_migrates_without_losing_existing_catalog(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    con = duckdb.connect(str(home / "catalog.duckdb"))
    apply_migrations(con, CATALOG_MIGRATIONS[:1])
    con.execute("INSERT INTO definitions VALUES ('underlying','TEST',1,'{}','hash','a','library',now())")
    con.close()
    a = DuckDBAdapter.open(home)
    try:
        assert a.schema_versions["catalog"] == len(CATALOG_MIGRATIONS)
        assert a.get_definition("underlying", "TEST").content_hash == "hash"
    finally:
        a.close()


def test_v2_home_keeps_its_run_rows_when_runs_gain_provenance(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    con = duckdb.connect(str(home / "catalog.duckdb"))
    apply_migrations(con, CATALOG_MIGRATIONS[:2])
    con.execute("INSERT INTO runs (run_id, status) VALUES ('run_old', 'completed')")
    con.close()
    a = DuckDBAdapter.open(home)
    try:
        assert a.schema_versions["catalog"] == 3
        assert a._cat.execute("SELECT status, spec_id FROM runs").fetchall() == [("completed", None)]
        assert a.page_runs().total == 0  # rows without provenance (Phase 7 test rows) are not listed as runs
    finally:
        a.close()


def test_coverage_calendar_quality_counts_and_nontrading_day(svc):
    stage(svc.storage, "old", (D1, date(2024, 1, 6)))  # Tuesday and Saturday
    svc.storage.commit_import("old", "replace")
    report = svc.coverage("SPX", date(2024, 1, 1), date(2024, 1, 7), CTX)
    assert [d.day.day for d in report.days] == [2, 3, 4, 5, 6]  # excludes New Year's holiday
    assert report.days[-1].trading_day is False
    m = report.months[0]
    assert (m.trading_days, m.covered_days, m.missing_days, m.non_trading_days) == (4, 1, 3, 1)
    assert m.contracts == 6 and m.flagged_days == 1
    assert report.days[0].snapshots[0].import_id == "old"
    assert svc.coverage("SPX", date(2024, 2, 1), date(2024, 2, 2), CTX).months[0].missing_days == 2


@pytest.mark.parametrize("values", [{}, {"import_id": "x", "underlying": "SPX"},
    {"underlying": "SPX", "start": D2, "end": D1}])
def test_invalid_selection(values):
    with pytest.raises(ValidationError):
        DataSelection(**values)



def test_concurrent_commits_keep_exactly_one_active_version(svc):
    a = svc.storage
    stage(a, "one")
    stage(a, "two")
    barrier = threading.Barrier(2)
    errors = []
    def commit(name):
        reader = a.reader()
        try:
            barrier.wait(timeout=5)
            reader.commit_import(name, "replace")
        except Exception as exc:
            errors.append(exc)
        finally:
            reader.close()
    threads = [threading.Thread(target=commit, args=(name,)) for name in ("one", "two")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert not any(thread.is_alive() for thread in threads) and not errors
    active = a.list_versions("SPX", states=[VersionState.ACTIVE])
    assert len(active) == 2 and len({v.import_id for v in active}) == 1


def test_delete_failure_rolls_back_flags_and_versions(svc, monkeypatch):
    a = svc.storage
    stage(a, "old")
    a.commit_import("old", "replace")
    seed_run(a, "run", "old")
    preview = a.preview_change("delete", selection())
    write = a._write
    def fail(sql, params):
        if sql.startswith("UPDATE runs"):
            raise RuntimeError("injected invalidation failure")
        return write(sql, params)
    monkeypatch.setattr(a, "_write", fail)
    with pytest.raises(RuntimeError):
        a.apply_change(preview)
    assert set(states(a).values()) == {VersionState.ACTIVE}
    assert svc.run_data_impacts("run") == []


def test_reopen_discards_interrupted_preparation_without_touching_original(tmp_path, monkeypatch):
    import pyarrow.parquet as pq
    home = tmp_path / "home"
    a = DuckDBAdapter.open(home)
    stage(a, "old")
    a.commit_import("old", "replace")
    a.apply_change(a.preview_change("delete", selection(D2, D2)))
    def crash(*args, **kwargs):
        raise SystemExit("interrupted during preparation")
    monkeypatch.setattr(pq, "write_table", crash)
    with pytest.raises(SystemExit):
        a.apply_change(a.preview_change("purge", selection()))
    a.close()
    monkeypatch.undo()
    reopened = DuckDBAdapter.open(home)
    try:
        assert reopened.read_import_snapshot("old", D2).num_rows == 3
        assert states(reopened)["old", D2] == VersionState.DELETED
        assert not list((home / "uploads").glob("files_*"))
    finally:
        reopened.close()


def test_background_purge_cancel_restores_replaced_file(svc, monkeypatch):
    import prophetovol.storage.duckdb.lifecycle as lifecycle
    a = svc.storage
    stage(a, "old")
    a.commit_import("old", "replace")
    a.apply_change(a.preview_change("delete", selection(D2, D2)))
    entered, release = threading.Event(), threading.Event()
    replace = lifecycle.os.replace
    def wait_after_replace(src, dst):
        replace(src, dst)
        if str(src).endswith(".new"):
            entered.set()
            assert release.wait(10)
    monkeypatch.setattr(lifecycle.os, "replace", wait_after_replace)
    preview = svc.preview_data_change("purge", selection(), CTX)
    svc.start_jobs(svc.job_handlers())
    job = svc.purge_data(preview, CTX, confirmed=True, background=True)
    assert entered.wait(5)
    try:
        svc.cancel_job(job.job_id, CTX)
    finally:
        release.set()
    assert svc.jobs.wait(job.job_id, 10)
    assert svc.get_job(job.job_id).status == JobStatus.CANCELLED
    assert a.read_import_snapshot("old", D2).num_rows == 3
    assert states(a)["old", D2] == VersionState.DELETED
