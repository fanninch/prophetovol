"""Adapter contract suite, Phase 3 part: lifecycle, definitions, imports, staged market data, jobs,
attempts and readers. Commit, overlap, delete, purge and point-in-time reads join in Phase 7; run
writes in Phase 14.
"""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta, timezone

import pyarrow as pa
import pytest

from prophetovol.core.context import CallContext, Channel
from prophetovol.core.errors import ImmutableEntityError, NotFoundError, ValidationFailed
from prophetovol.core.records import (AttemptOutcome, AttemptRecord, DataImport, DataVersionRecord, ImportFile,
                                      ImportStatus, JobRecord, JobStatus, VersionState)

CTX = CallContext(actor="alice", channel=Channel.CLI)
T0 = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def make_import(import_id: str, *, underlying: str = "SPX", created: datetime = T0,
                files: list[ImportFile] | None = None) -> DataImport:
    return DataImport(import_id=import_id, underlying=underlying, data_source="ivolatility_eod",
                      status=ImportStatus.INGESTING,
                      files=files or [ImportFile(name="a.csv", size_bytes=10, sha256="aa" * 32),
                                      ImportFile(name="b.csv", size_bytes=20, sha256="bb" * 32)],
                      actor="alice", channel=Channel.CLI, created_at=created)


def snapshot_table(day: date, n: int = 3) -> pa.Table:
    as_of = datetime(day.year, day.month, day.day, 20, 15, tzinfo=timezone.utc)
    return pa.table({
        "as_of_date": pa.array([day] * n, pa.date32()),
        "as_of": pa.array([as_of] * n, pa.timestamp("us", tz="UTC")),
        "strike": pa.array([5000.0 + 5 * i for i in range(n)]),
        "bid": pa.array([1.0 + i for i in range(n)]),
    })


def version(import_id: str, day: date, contracts: int = 3) -> DataVersionRecord:
    return DataVersionRecord(underlying="SPX", as_of=datetime(day.year, day.month, day.day, 20, 15, tzinfo=timezone.utc),
                             as_of_date=day, import_id=import_id, state=VersionState.STAGED, contracts=contracts,
                             quality_flags=["crossed_quote"] if day.day == 2 else [], state_changed_at=T0)


class TestLifecycle:
    def test_new_home_is_created_and_migrated(self, adapter):
        assert adapter.schema_versions == {"catalog": 3, "results": 2}
        assert (adapter.home / "market").is_dir()

    def test_reopening_keeps_data(self, open_adapter, tmp_path):
        a = open_adapter(tmp_path / "home")
        a.save_definition("underlying", "SPX", {"x": 1}, CTX)
        a.close()
        b = open_adapter(tmp_path / "home")
        assert b.get_definition("underlying", "SPX").body == {"x": 1}
        assert b.schema_versions == {"catalog": 3, "results": 2}
        b.close()


class TestDefinitions:
    def test_versions_and_unchanged_content(self, adapter):
        v1, created = adapter.save_definition("underlying", "SPX", {"a": 1, "b": [1, 2]}, CTX)
        assert created and v1.version == 1 and len(v1.content_hash) == 64
        same, created = adapter.save_definition("underlying", "SPX", {"b": [1, 2], "a": 1}, CTX)
        assert not created and same.version == 1  # key order does not matter (canonical JSON)
        v2, created = adapter.save_definition("underlying", "SPX", {"a": 2}, CTX)
        assert created and v2.version == 2
        assert adapter.get_definition("underlying", "SPX").version == 2
        assert adapter.get_definition("underlying", "SPX", 1).body == {"a": 1, "b": [1, 2]}
        assert [v.version for v in adapter.list_definition_versions("underlying", "SPX")] == [1, 2]
        assert v1.actor == "alice" and v1.channel is Channel.CLI and v1.created_at.tzinfo is not None

    def test_latest_of_each_key_in_key_order(self, adapter):
        for key, body in [("SPX", {"v": 1}), ("NDX", {"v": 1}), ("SPX", {"v": 2})]:
            adapter.save_definition("underlying", key, body, CTX)
        adapter.save_definition("data_source", "ivolatility_eod", {"v": 1}, CTX)
        latest = adapter.list_definitions("underlying")
        assert [(d.key, d.version) for d in latest] == [("NDX", 1), ("SPX", 2)]

    def test_missing(self, adapter):
        with pytest.raises(NotFoundError):
            adapter.get_definition("underlying", "XYZ")
        adapter.save_definition("underlying", "SPX", {"v": 1}, CTX)
        with pytest.raises(NotFoundError, match="no version 5"):
            adapter.get_definition("underlying", "SPX", 5)


class TestImports:
    def test_round_trip_and_update(self, adapter):
        adapter.create_import(make_import("imp_1"))
        got = adapter.get_import("imp_1")
        assert got.status is ImportStatus.INGESTING and [f.name for f in got.files] == ["a.csv", "b.csv"]
        assert got.created_at == T0
        got.status, got.rows, got.underlying = ImportStatus.STAGED, 1234, "NDX"
        got.first_as_of_date, got.last_as_of_date = date(2024, 1, 2), date(2024, 3, 28)
        got.quality_report = {"checks": [{"check": "zero_ask", "count": 3}]}
        adapter.update_import(got)
        again = adapter.get_import("imp_1")
        assert (again.status, again.rows, again.last_as_of_date) == (ImportStatus.STAGED, 1234, date(2024, 3, 28))
        assert again.underlying == "NDX"
        assert again.quality_report["checks"][0]["count"] == 3

    def test_paging_newest_first_with_filter(self, adapter):
        for i in range(5):
            adapter.create_import(make_import(f"imp_{i}", underlying="SPX" if i % 2 == 0 else "NDX",
                                              created=T0 + timedelta(minutes=i)))
        page = adapter.page_imports(offset=1, limit=2)
        assert page.total == 5 and [i.import_id for i in page.items] == ["imp_3", "imp_2"]
        spx = adapter.page_imports(underlying="SPX")
        assert spx.total == 3 and [i.import_id for i in spx.items] == ["imp_4", "imp_2", "imp_0"]

    def test_bad_paging_is_rejected(self, adapter):
        with pytest.raises(ValidationFailed):
            adapter.page_imports(offset=-1)
        with pytest.raises(ValidationFailed):
            adapter.page_jobs(limit=501)

    def test_unknown_import(self, adapter):
        with pytest.raises(NotFoundError):
            adapter.get_import("imp_none")
        with pytest.raises(NotFoundError):
            adapter.update_import(make_import("imp_none"))

    def test_find_by_file_hash_ignores_discarded(self, adapter):
        adapter.create_import(make_import("imp_a"))
        adapter.create_import(make_import("imp_b", created=T0 + timedelta(seconds=1)))
        assert adapter.find_imports_with_file_hash("bb" * 32) == ["imp_a", "imp_b"]
        adapter.discard_import("imp_a")
        assert adapter.find_imports_with_file_hash("bb" * 32) == ["imp_b"]
        assert adapter.find_imports_with_file_hash("cc" * 32) == []


class TestStagedMarketData:
    def stage(self, adapter, import_id="imp_1"):
        adapter.create_import(make_import(import_id))
        adapter.write_market_partition(import_id, "SPX", 2024, 1, snapshot_table(date(2024, 1, 2)))
        adapter.write_market_partition(import_id, "SPX", 2024, 2, snapshot_table(date(2024, 2, 1), n=5))
        adapter.record_staged_versions([version(import_id, date(2024, 1, 2)), version(import_id, date(2024, 2, 1), 5)])

    def test_stage_list_and_read(self, adapter):
        self.stage(adapter)
        versions = adapter.list_versions("SPX")
        assert [(v.as_of_date, v.state, v.contracts) for v in versions] == [
            (date(2024, 1, 2), VersionState.STAGED, 3), (date(2024, 2, 1), VersionState.STAGED, 5)]
        assert versions[0].quality_flags == ["crossed_quote"]
        assert versions[0].as_of == datetime(2024, 1, 2, 20, 15, tzinfo=timezone.utc)
        snap = adapter.read_import_snapshot("imp_1", date(2024, 2, 1), ["strike", "bid"])
        assert snap.column_names == ["strike", "bid"] and snap.num_rows == 5
        assert adapter.read_import_snapshot("imp_1", date(2024, 2, 1)).num_columns == 4
        assert adapter.read_import_snapshot("imp_1", date(2024, 5, 1)).num_rows == 0

    def test_filters(self, adapter):
        self.stage(adapter)
        self.stage(adapter, "imp_2")
        assert len(adapter.list_versions("SPX", import_id="imp_2")) == 2
        assert adapter.list_versions("SPX", states=[VersionState.ACTIVE]) == []
        assert adapter.list_versions("NDX") == []

    def test_a_partition_is_written_once(self, adapter):
        self.stage(adapter)
        with pytest.raises(ImmutableEntityError):
            adapter.write_market_partition("imp_1", "SPX", 2024, 1, snapshot_table(date(2024, 1, 3)))

    def test_discard_removes_files_and_marks_everything(self, adapter):
        self.stage(adapter)
        adapter.discard_import("imp_1")
        assert adapter.get_import("imp_1").status is ImportStatus.DISCARDED
        assert {v.state for v in adapter.list_versions("SPX")} == {VersionState.DISCARDED}
        assert adapter.read_import_snapshot("imp_1", date(2024, 1, 2)).num_rows == 0
        assert not list((adapter.home / "market").rglob("imp_1.parquet"))


class TestJobs:
    def test_round_trip_update_and_paging(self, adapter):
        for i in range(3):
            adapter.insert_job(JobRecord(job_id=f"job_{i}", kind="ingest", params={"files": ["a.csv"]},
                                         status=JobStatus.QUEUED, actor="alice", channel=Channel.CLI,
                                         created_at=T0 + timedelta(seconds=i)))
        job = adapter.get_job("job_1")
        job.status, job.progress_done, job.progress_total, job.progress_label = JobStatus.RUNNING, 3, 12, "2024-03"
        job.started_at = T0 + timedelta(minutes=1)
        adapter.update_job(job)
        got = adapter.get_job("job_1")
        assert (got.status, got.progress_done, got.progress_label) == (JobStatus.RUNNING, 3, "2024-03")
        assert got.params == {"files": ["a.csv"]} and got.started_at == T0 + timedelta(minutes=1)
        running = adapter.page_jobs(statuses=[JobStatus.RUNNING])
        assert running.total == 1 and running.items[0].job_id == "job_1"
        assert [j.job_id for j in adapter.page_jobs().items] == ["job_2", "job_1", "job_0"]
        with pytest.raises(NotFoundError):
            adapter.get_job("job_none")


class TestAttempts:
    def test_append_only_paging_and_filter(self, adapter):
        for i, (op, outcome) in enumerate([("data.import", AttemptOutcome.OK), ("data.delete", AttemptOutcome.REJECTED),
                                           ("data.import", AttemptOutcome.ERROR)]):
            adapter.append_attempt(AttemptRecord(attempt_id=f"att_{i}", operation=op, params_summary={"i": i},
                                                 outcome=outcome, reasons=["runs read this data"] if i == 1 else [],
                                                 actor="alice", channel=Channel.API, attempted_at=T0 + timedelta(seconds=i)))
        page = adapter.page_attempts()
        assert [a.attempt_id for a in page.items] == ["att_2", "att_1", "att_0"]
        rejected = page.items[1]
        assert rejected.outcome is AttemptOutcome.REJECTED and rejected.reasons == ["runs read this data"]
        assert adapter.page_attempts(operation="data.import").total == 2
        assert not hasattr(adapter, "update_attempt") and not hasattr(adapter, "delete_attempt")


class TestReaders:
    def test_reader_sees_committed_writes_and_closing_it_keeps_owner(self, adapter):
        adapter.create_import(make_import("imp_1"))
        reader = adapter.reader()
        assert reader.get_import("imp_1").import_id == "imp_1"
        reader.close()
        assert adapter.get_import("imp_1").import_id == "imp_1"

    def test_readers_on_other_threads_while_owner_writes(self, adapter):
        errors, counts = [], []

        def read():
            r = adapter.reader()
            try:
                for _ in range(20):
                    counts.append(r.page_jobs().total)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                r.close()

        threads = [threading.Thread(target=read) for _ in range(3)]
        for t in threads:
            t.start()
        for i in range(20):
            adapter.insert_job(JobRecord(job_id=f"job_{i}", kind="ingest", status=JobStatus.QUEUED, actor="a",
                                         channel=Channel.CLI, created_at=T0))
        for t in threads:
            t.join()
        assert not errors and counts and max(counts) <= 20
