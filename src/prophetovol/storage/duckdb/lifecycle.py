"""DuckDB data lifecycle transactions and recoverable Parquet purges.

A shared lock serializes lifecycle writes and file reads across the owner's cursors. Purge
backs up affected files and persists a manifest before replacing them. The catalog transaction
records its operation id: reopening restores uncommitted files or removes committed backups.
"""

from __future__ import annotations

from collections.abc import Callable

import functools
import json
import os
import shutil
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq

from prophetovol.core.errors import ImmutableEntityError, PointInTimeError, ValidationFailed, ValidationIssue
from prophetovol.core.ids import content_hash, new_id, utc_now
from prophetovol.core.records import ImportStatus, VersionState
from prophetovol.data.lifecycle import ChangePreview, CommitChoice, DataSelection, OverlapItem, RunImpact


def _locked(method):
    """Serialize an adapter operation across its reader cursors."""
    @functools.wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lifecycle_lock:
            return method(self, *args, **kwargs)
    return wrapped


def _ts(value):
    """Convert an aware instant to the catalog's naive UTC representation."""
    if value.tzinfo is None:
        raise ValueError("instants must be timezone-aware")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


class _LifecycleStorage:
    """Lifecycle implementation mixed into the DuckDB adapter."""

    @_locked
    def overlap(self, import_id: str) -> list[OverlapItem]:
        """Compare every staged snapshot with currently active data (DATA-30).

        :param import_id: A staged import.
        :returns: Incoming versions paired with their active overlaps, ordered by as-of.
        """
        record = self.get_import(import_id)
        if record.status != ImportStatus.STAGED:
            raise ImmutableEntityError("only staged imports can be committed or reviewed for overlap")
        active = {v.as_of: v for v in self.list_versions(record.underlying, states=[VersionState.ACTIVE])}
        return [OverlapItem(incoming=v, active=active.get(v.as_of))
                for v in self.list_versions(record.underlying, import_id, [VersionState.STAGED])]

    def _set_state(self, versions, state):
        """Change exactly these version identities, inside the caller's transaction."""
        now = _ts(utc_now())
        for v in versions:
            self._write("""UPDATE data_versions SET state = ?, state_changed_at = ?
                WHERE underlying = ? AND as_of = ? AND import_id = ?""",
                [state.value, now, v.underlying, _ts(v.as_of), v.import_id])

    def _dependencies(self, versions):
        """Read run dependencies of exact version identities using Ibis."""
        if not versions:
            return []
        t = self._ibis.table("run_data_versions")
        keys = {(v.underlying, _ts(v.as_of), v.import_id): v for v in versions}
        # Restrict in SQL before materializing; filter the exact identities below.
        rows = self._rows(t.filter(t.import_id.isin(sorted({v.import_id for v in versions})))
                          .order_by(["run_id", "underlying", "as_of", "import_id"]))
        return [(r, keys[(r["underlying"], r["as_of"], r["import_id"])]) for r in rows
                if (r["underlying"], r["as_of"], r["import_id"]) in keys]

    def _impacts(self, versions):
        """Group dependent run dates for a review report."""
        grouped = {}
        for r, v in self._dependencies(versions):
            grouped.setdefault((r["run_id"], v.underlying), set()).add(v.as_of_date)
        return [RunImpact(run_id=key[0], underlying=key[1], dates=sorted(days))
                for key, days in sorted(grouped.items())]

    def _invalidate(self, versions):
        """Apply invalidation in the same transaction as activation or deactivation."""
        for r, v in self._dependencies(versions):
            self._write("""INSERT INTO run_invalidations VALUES (?, ?, ?, ?, ?)
                ON CONFLICT DO NOTHING""", [r["run_id"], v.underlying, _ts(v.as_of), v.import_id, v.as_of_date])
            self._write("UPDATE runs SET data_superseded = TRUE WHERE run_id = ?", [r["run_id"]])

    @_locked
    def run_data_impacts(self, run_id: str) -> list[RunImpact]:
        """Read the persisted superseded-data dates of a run (RUN-40).

        :param run_id: Run whose flags are requested.
        :returns: Affected dates grouped by underlying; empty if no invalidations exist.
        """
        t = self._ibis.table("run_invalidations")
        rows = self._rows(t.filter(t.run_id == run_id).order_by(["underlying", "as_of_date"]))
        grouped = {}
        for r in rows:
            grouped.setdefault(r["underlying"], set()).add(r["as_of_date"])
        return [RunImpact(run_id=run_id, underlying=u, dates=sorted(days)) for u, days in sorted(grouped.items())]

    def _transaction(self, action):
        """Run catalog mutations atomically, including on injected write failures."""
        self._cat.execute("BEGIN TRANSACTION")
        try:
            result = action()
            self._cat.execute("COMMIT")
            return result
        except Exception:
            self._cat.execute("ROLLBACK")
            raise

    @_locked
    def commit_import(self, import_id: str, choice: CommitChoice) -> int:
        """Activate an import atomically, preserving old versions and invalidating dependent runs.

        :param import_id: Staged import to commit.
        :param choice: Replace overlaps, add new dates only, or cancel/discard.
        :returns: Number of snapshots activated.
        """
        choice = CommitChoice(choice)
        pairs = self.overlap(import_id)
        if choice == CommitChoice.CANCEL:
            self.discard_import(import_id)
            return 0
        def apply():
            activate = [p.incoming for p in pairs if choice == CommitChoice.REPLACE or p.active is None]
            replaced = [p.active for p in pairs if choice == CommitChoice.REPLACE and p.active is not None]
            skipped = [p.incoming for p in pairs if choice == CommitChoice.ADD_NEW and p.active is not None]
            self._set_state(replaced + skipped, VersionState.SUPERSEDED)
            self._set_state(activate, VersionState.ACTIVE)
            self._invalidate(replaced)
            self._write("UPDATE imports SET status = ?, commit_choice = ?, committed_at = ? WHERE import_id = ?",
                        [ImportStatus.COMMITTED.value, choice.value, _ts(utc_now()), import_id])
            return len(activate)
        return self._transaction(apply)

    @_locked
    def preview_change(self, operation: str, selection: DataSelection) -> ChangePreview:
        """List eligible versions and dependent runs before delete or purge (DATA-52).

        :param operation: ``delete`` or ``purge``.
        :param selection: Import for purge, or inclusive underlying/date range.
        :returns: Review report with a token that detects intervening changes.
        """
        if operation not in ("delete", "purge") or (operation == "delete" and selection.import_id is not None):
            raise ValidationFailed([ValidationIssue("selection", "delete needs an underlying/date range; purge accepts either")])
        underlying = (self.get_import(selection.import_id).underlying if selection.import_id is not None
                      else selection.underlying)
        states = [VersionState.ACTIVE] if operation == "delete" else [VersionState.SUPERSEDED, VersionState.DELETED]
        versions = self.list_versions(underlying, selection.import_id, states)
        if selection.import_id is None:
            versions = [v for v in versions if selection.start <= v.as_of_date <= selection.end]
        runs = self._impacts(versions)
        body = dict(operation=operation, selection=selection.model_dump(mode="json"),
                    versions=[v.model_dump(mode="json") for v in versions], runs=[r.model_dump(mode="json") for r in runs])
        return ChangePreview(**body, token=content_hash(body))

    @_locked
    def apply_change(self, preview: ChangePreview, progress: Callable[[int, int], None] | None = None) -> int:
        """Execute a confirmed preview, rejecting a changed scope before touching data.

        :param preview: The report the caller confirmed, including its original token.
        :param progress: Optional progress/cancellation callback between purge files; receives done and total.
        :returns: Number of versions deleted or purged.
        :raises ValidationFailed: If versions or dependent runs changed after review.
        """
        current = self.preview_change(preview.operation, preview.selection)
        if current.token != preview.token:
            raise ValidationFailed([ValidationIssue("confirmation", "data or affected runs changed; review and confirm again")])
        versions = current.versions
        def apply():
            self._set_state(versions, VersionState.DELETED if preview.operation == "delete" else VersionState.PURGED)
            self._invalidate(versions)
        if preview.operation == "delete":
            self._transaction(apply)
        else:
            removals = {}
            for v in versions:
                path = self._partition_dir(v.underlying, v.as_of_date.year, v.as_of_date.month) / f"{v.import_id}.parquet"
                removals.setdefault(path, []).append(v)
            self._file_transaction(removals, apply, progress)
        return len(versions)

    def _file_transaction(self, removals, action, progress=None):
        """Prepare per-file backups and rewrites, then commit files and catalog with a recovery journal."""
        operation_id = new_id("files")
        work = self.home / "uploads" / operation_id
        work.mkdir(parents=True)
        entries = []
        manifest_written = False
        try:
            for n, (path, versions) in enumerate(sorted(removals.items())):
                if progress is not None:
                    progress(n, 2 * len(removals))
                # Only adapter-generated paths beneath market are eligible.
                path.resolve().relative_to((self.home / "market").resolve())
                backup, replacement = work / f"{n}.bak", work / f"{n}.new"
                shutil.copy2(path, backup)
                keep = None
                if versions is not None:
                    t = self._ibis.read_parquet(str(path), hive_partitioning=False)
                    # Market timestamps are UTC-aware; compare with aware literals.
                    keep = t.filter(~t.as_of.isin([v.as_of for v in versions])).to_pyarrow()
                    if keep.num_rows:
                        pq.write_table(keep, replacement, row_group_size=20_000, compression="zstd")
                entries.append({"path": path.relative_to(self.home).as_posix(), "backup": backup.name,
                                "replacement": replacement.name if keep is not None and keep.num_rows else None})
            with open(work / "manifest.tmp", "w", encoding="utf-8") as handle:
                json.dump(entries, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(work / "manifest.tmp", work / "manifest.json")
            manifest_written = True
            def apply():
                for n, entry in enumerate(entries):
                    if progress is not None:
                        progress(len(entries) + n, 2 * len(entries))
                    target = self.home / entry["path"]
                    if entry["replacement"]:
                        os.replace(work / entry["replacement"], target)
                    else:
                        target.unlink()
                if progress is not None:
                    progress(2 * len(entries), 2 * len(entries))
                action()
                self._write("INSERT INTO file_operations VALUES (?)", [operation_id])
            self._transaction(apply)
        except Exception:
            if manifest_written:
                self._recover_file_operation(work)
            else:
                shutil.rmtree(work, ignore_errors=True)
            raise
        else:
            shutil.rmtree(work, ignore_errors=True)

    def _recover_file_operation(self, work):
        """Restore uncommitted originals or clean a committed operation's backups, idempotently."""
        manifest = work / "manifest.json"
        if not manifest.exists():
            shutil.rmtree(work)
            return
        t = self._ibis.table("file_operations")
        committed = bool(self._rows(t.filter(t.operation_id == work.name)))
        if not committed:
            for entry in json.loads(manifest.read_text(encoding="utf-8")):
                target = self.home / entry["path"]
                target.resolve().relative_to((self.home / "market").resolve())
                backup = work / entry["backup"]
                backup.resolve().relative_to(work.resolve())
                shutil.copy2(backup, target)
        shutil.rmtree(work)

    def _recover_files(self):
        """Recover interrupted file transactions before opening the home to callers."""
        for work in sorted((self.home / "uploads").glob("files_*")):
            self._recover_file_operation(work)

    @_locked
    def read_active_snapshot(self, underlying: str, as_of: datetime, columns: list[str] | None = None,
                             cutoff: datetime | None = None) -> pa.Table:
        """Read only the active version at the exact as-of instant, with an optional point-in-time guard.

        :param underlying: Underlying to read.
        :param as_of: Requested aware snapshot instant; no implicit carry-forward.
        :param columns: Columns to return; all when omitted.
        :param cutoff: Latest allowed aware instant; asking for later data raises PointInTimeError.
        :returns: Active rows or an empty table when no snapshot is active.
        """
        _ts(as_of)
        if cutoff is not None:
            _ts(cutoff)
            if as_of > cutoff:
                raise PointInTimeError("requested market snapshot is after the as-of cutoff")
        versions = [v for v in self.list_versions(underlying, states=[VersionState.ACTIVE]) if v.as_of == as_of]
        if not versions:
            return pa.table({})
        v = versions[0]
        path = self._partition_dir(underlying, v.as_of_date.year, v.as_of_date.month) / f"{v.import_id}.parquet"
        t = self._ibis.read_parquet(str(path), hive_partitioning=False)
        registry = self._ibis.table("data_versions")
        registry = registry.filter((registry.underlying == underlying) & (registry.state == "active")
                                   & (registry.import_id == v.import_id) & (registry.as_of == _ts(as_of)))
        # Each file belongs to one import. Join its timestamps to that import's active registry rows.
        active = registry.select(as_of=registry.as_of.cast(t.schema()["as_of"]))
        expr = t.filter(t.as_of == as_of).semi_join(active, "as_of")
        if columns is not None:
            expr = expr.select(columns)
        return expr.to_pyarrow()
