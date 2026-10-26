"""Phase 7 storage contract: active versions, overlap, deletion, purge and point-in-time reads."""

from datetime import date, timedelta

import pyarrow as pa
import pytest

from prophetovol.core.errors import ImmutableEntityError, PointInTimeError, ValidationFailed
from prophetovol.core.records import ImportStatus, VersionState
from prophetovol.data.lifecycle import CommitChoice, DataSelection
from tests.contract.test_adapter_contract import make_import, snapshot_table, version

D1, D2, D3 = date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)


def stage(adapter, name, days=(D1, D2), n=3):
    record = make_import(name)
    record.status = ImportStatus.STAGED
    record.quality_report = {"checks": []}
    adapter.create_import(record)
    months = {}
    for day in days:
        months.setdefault((day.year, day.month), []).append(snapshot_table(day, n))
    for (year, month), tables in months.items():
        adapter.write_market_partition(name, "SPX", year, month, pa.concat_tables(tables))
    adapter.record_staged_versions([version(name, d, n) for d in days])


def selection(start=D1, end=D2):
    return DataSelection(underlying="SPX", start=start, end=end)


def states(adapter):
    return {(v.import_id, v.as_of_date): v.state for v in adapter.list_versions("SPX")}


def test_overlap_and_replace_preserve_old_data(adapter):
    stage(adapter, "old")
    assert adapter.read_active_snapshot("SPX", version("old", D1).as_of).num_rows == 0
    assert adapter.commit_import("old", CommitChoice.REPLACE) == 2
    stage(adapter, "new", (D2, D3), n=5)
    report = adapter.overlap("new")
    assert [(p.incoming.contracts, p.active.import_id if p.active else None) for p in report] == [(5, "old"), (5, None)]
    assert report[0].active.contracts == 3
    assert adapter.commit_import("new", CommitChoice.REPLACE) == 2
    assert states(adapter) == {("old", D1): VersionState.ACTIVE, ("old", D2): VersionState.SUPERSEDED,
                               ("new", D2): VersionState.ACTIVE, ("new", D3): VersionState.ACTIVE}
    assert adapter.read_import_snapshot("old", D2).num_rows == 3
    assert adapter.read_active_snapshot("SPX", version("new", D2).as_of, ["bid"]).num_rows == 5
    assert adapter.get_import("new").commit_choice == "replace"
    assert adapter.get_import("new").committed_at.tzinfo is not None


def test_add_new_keeps_overlap_inactive_and_purgeable(adapter):
    stage(adapter, "old")
    adapter.commit_import("old", "replace")
    stage(adapter, "new", (D2, D3), n=5)
    assert adapter.commit_import("new", "add_new") == 1
    assert states(adapter)["new", D2] == VersionState.SUPERSEDED
    assert adapter.read_active_snapshot("SPX", version("old", D2).as_of).num_rows == 3
    preview = adapter.preview_change("purge", DataSelection(import_id="new"))
    assert [v.as_of_date for v in preview.versions] == [D2]
    assert adapter.apply_change(preview) == 1
    assert adapter.read_import_snapshot("new", D2).num_rows == 0
    assert adapter.read_active_snapshot("SPX", version("new", D3).as_of).num_rows == 5


def test_all_overlap_add_new_cannot_be_committed_or_discarded_again(adapter):
    for name in ("old", "new"):
        stage(adapter, name)
        adapter.commit_import(name, "add_new")
    with pytest.raises(ImmutableEntityError):
        adapter.commit_import("new", "replace")
    with pytest.raises(ImmutableEntityError):
        adapter.discard_import("new")


def test_cancel_discards_files_and_records_choice(adapter):
    stage(adapter, "cancel")
    assert adapter.commit_import("cancel", "cancel") == 0
    assert adapter.get_import("cancel").status == ImportStatus.DISCARDED
    assert adapter.get_import("cancel").commit_choice == "cancel"
    assert adapter.get_import("cancel").quality_report == {"checks": []}
    assert set(states(adapter).values()) == {VersionState.DISCARDED}
    assert not list((adapter.home / "market").rglob("*.parquet"))


def test_delete_keeps_files_and_does_not_reactivate_superseded_versions(adapter):
    for name in ("old", "new"):
        stage(adapter, name)
        adapter.commit_import(name, "replace")
    preview = adapter.preview_change("delete", selection(D2, D2))
    assert [(v.import_id, v.as_of_date) for v in preview.versions] == [("new", D2)]
    assert adapter.apply_change(preview) == 1
    assert adapter.read_active_snapshot("SPX", version("new", D2).as_of).num_rows == 0
    assert adapter.read_import_snapshot("new", D2).num_rows == 3
    assert states(adapter)["old", D2] == VersionState.SUPERSEDED
    assert states(adapter)["new", D1] == VersionState.ACTIVE


def test_purge_rewrites_partial_files_and_reclaims_whole_files(adapter):
    stage(adapter, "old", (D1, D2, date(2024, 2, 1)))
    adapter.commit_import("old", "replace")
    adapter.apply_change(adapter.preview_change("delete", selection(D2, date(2024, 2, 1))))
    assert adapter.apply_change(adapter.preview_change("purge", DataSelection(import_id="old"))) == 2
    assert adapter.read_import_snapshot("old", D1).num_rows == 3
    assert adapter.read_import_snapshot("old", D2).num_rows == 0
    assert len(list((adapter.home / "market").rglob("*.parquet"))) == 1
    assert adapter.get_import("old").quality_report == {"checks": []}
    assert adapter.apply_change(adapter.preview_change("purge", DataSelection(import_id="old"))) == 0


def test_purge_never_removes_active_or_staged_versions(adapter):
    stage(adapter, "active")
    adapter.commit_import("active", "replace")
    stage(adapter, "staged")
    assert adapter.preview_change("purge", selection()).versions == []
    assert adapter.preview_change("purge", DataSelection(import_id="staged")).versions == []
    assert adapter.read_import_snapshot("staged", D1).num_rows == 3


def test_stale_preview_refused_without_changing_data(adapter):
    stage(adapter, "old")
    adapter.commit_import("old", "replace")
    before = adapter.preview_change("delete", selection())
    stage(adapter, "new")
    adapter.commit_import("new", "replace")
    with pytest.raises(ValidationFailed, match="review and confirm again"):
        adapter.apply_change(before)
    assert states(adapter)["new", D1] == VersionState.ACTIVE


def test_point_in_time_guard_and_exact_instant(adapter):
    stage(adapter, "old")
    adapter.commit_import("old", "replace")
    instant = version("old", D2).as_of
    with pytest.raises(PointInTimeError):
        adapter.read_active_snapshot("SPX", instant, cutoff=instant-timedelta(seconds=1))
    assert adapter.read_active_snapshot("SPX", instant, cutoff=instant).num_rows == 3
    assert adapter.read_active_snapshot("SPX", instant+timedelta(seconds=1)).num_rows == 0
    assert adapter.read_active_snapshot("NDX", instant).num_rows == 0
    with pytest.raises(ValueError, match="timezone-aware"):
        adapter.read_active_snapshot("SPX", instant.replace(tzinfo=None))


def test_delete_rejects_import_selection(adapter):
    stage(adapter, "old")
    with pytest.raises(ValidationFailed):
        adapter.preview_change("delete", DataSelection(import_id="old"))
