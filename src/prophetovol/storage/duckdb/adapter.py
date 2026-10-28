"""The DuckDB and Parquet storage adapter (DATA-80 to DATA-83, ARC-4).

Layout under the home directory:

* ``catalog.duckdb``: definitions, imports, data versions, jobs, attempts
* ``results.duckdb``: run output (from Phase 14)
* ``market/underlying=<U>/year=<YYYY>/month=<MM>/<import_id>.parquet``: market snapshots, one file per
  import per month (DATA-80)

Reads are Ibis expressions (DATA-81); writes are DuckDB SQL or Parquet files, which only this
module knows about (DATA-83).
"""

from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import ibis
import pyarrow as pa
import pyarrow.parquet as pq

from prophetovol.core.context import CallContext
from prophetovol.core.errors import HomeLockedError, ImmutableEntityError, NotFoundError
from prophetovol.core.ids import content_hash, utc_now
from prophetovol.core.paging import Page, check_page
from prophetovol.core.records import (AttemptRecord, DataImport, DataVersionRecord, DefinitionVersion, ImportFile,
                                      ImportStatus, JobRecord, JobStatus, VersionState)
from prophetovol.data.schema import SORT_KEYS
from prophetovol.storage.adapter import StorageAdapter
from prophetovol.storage.duckdb.lifecycle import _LifecycleStorage, _locked
from prophetovol.storage.duckdb.runs import _RunStorage
from prophetovol.storage.duckdb.schema import CATALOG_MIGRATIONS, RESULTS_MIGRATIONS, apply_migrations, schema_version

CATALOG_FILE = "catalog.duckdb"
"""The catalog database's file name in the home directory."""

RESULTS_FILE = "results.duckdb"
"""The results database's file name in the home directory."""

MARKET_DIR = "market"
"""The folder of market snapshot files in the home directory."""

ROW_GROUP_SIZE = 20_000
"""Rows per Parquet row group in market files (plan §4.2)."""


def _db_ts(value: datetime | None) -> datetime | None:
    """Convert an aware datetime to the naive UTC value stored in the databases.

    :param value: An aware datetime, or ``None``.
    :returns: The naive UTC datetime, or ``None``.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("instants must be timezone-aware")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _utc(value: datetime | None) -> datetime | None:
    """Convert a stored naive UTC datetime back to an aware one.

    :param value: The stored value, or ``None``.
    :returns: The aware UTC datetime, or ``None``.
    """
    return None if value is None else value.replace(tzinfo=timezone.utc)


def _json(value: Any) -> str | None:
    """Serialize a value for a JSON text column.

    :param value: JSON-compatible data, or ``None``.
    :returns: The JSON text, or ``None``.
    """
    return None if value is None else json.dumps(value, sort_keys=True)


def _unjson(text: str | None) -> Any:
    """Parse a JSON text column.

    :param text: The stored text, or ``None``.
    :returns: The data, or ``None``.
    """
    return None if text is None else json.loads(text)


def _connect(path: Path, home: Path) -> duckdb.DuckDBPyConnection:
    """Open a database file read-write, reporting a lock held by another process clearly (INT-41).

    :param path: The database file.
    :param home: The home directory, for the message.
    :returns: The connection.
    :raises HomeLockedError: If another process holds the file.
    """
    try:
        return duckdb.connect(str(path))
    except duckdb.IOException as exc:
        text = str(exc).lower()
        if "used by another process" in text or "already open" in text or "lock" in text:
            raise HomeLockedError(
                f"The home directory {home} is in use by another ProphetoVol process (for example "
                "`prophetovol serve`). Only one process can open a home directory at a time: stop the "
                "other process, or use a different --home.") from exc
        raise


class DuckDBAdapter(_LifecycleStorage, _RunStorage, StorageAdapter):
    """Storage in DuckDB databases and Parquet files under a home directory.

    Use :meth:`open` to create the owner; :meth:`reader` gives adapters for other threads.

    :param home: The home directory.
    :param catalog: A connection or cursor to ``catalog.duckdb``.
    :param results: A connection or cursor to ``results.duckdb``.
    :param owner: Whether this adapter owns the connections (and closes the databases on close).
    """

    def __init__(self, home: Path, catalog: duckdb.DuckDBPyConnection, results: duckdb.DuckDBPyConnection,
                 owner: bool) -> None:
        self._home = home
        self._cat = catalog
        self._res = results
        self._owner = owner
        self._ibis = ibis.duckdb.from_connection(catalog)
        self._ibis_res = ibis.duckdb.from_connection(results)
        self._closed = False
        self._lifecycle_lock = threading.RLock()

    @classmethod
    def open(cls, home: Path) -> DuckDBAdapter:
        """Open (creating if needed) the databases of a home directory and migrate them.

        :param home: The home directory; it and its folders are created if missing.
        :returns: The owning adapter.
        :raises HomeLockedError: If another process has the home directory open.
        """
        home = Path(home)
        for folder in (home, home / MARKET_DIR, home / "uploads", home / "logs"):
            folder.mkdir(parents=True, exist_ok=True)
        catalog = _connect(home / CATALOG_FILE, home)
        try:
            results = _connect(home / RESULTS_FILE, home)
        except Exception:
            catalog.close()
            raise
        apply_migrations(catalog, CATALOG_MIGRATIONS)
        apply_migrations(results, RESULTS_MIGRATIONS)
        adapter = cls(home, catalog, results, owner=True)
        try:
            adapter._recover_files()
        except Exception:
            adapter.close()
            raise
        return adapter

    # --- lifecycle -------------------------------------------------------------------------

    @property
    def home(self) -> Path:
        """The home directory this adapter stores in."""
        return self._home

    @property
    def schema_versions(self) -> dict[str, int]:
        """The schema version of each database."""
        return {"catalog": schema_version(self._cat), "results": schema_version(self._res)}

    def reader(self) -> DuckDBAdapter:
        """An adapter on new cursors of the same databases, for another thread (ARC-4).

        :returns: The reader adapter.
        """
        reader = DuckDBAdapter(self._home, self._cat.cursor(), self._res.cursor(), owner=False)
        reader._lifecycle_lock = self._lifecycle_lock
        return reader

    def close(self) -> None:
        """Close this adapter's connections or cursors."""
        if self._closed:
            return
        self._closed = True
        self._cat.close()
        self._res.close()

    # --- helpers -----------------------------------------------------------------------------

    def _rows(self, expr: ibis.Table) -> list[dict[str, Any]]:
        """Execute an Ibis table expression and return its rows as dicts.

        :param expr: The expression.
        :returns: The rows.
        """
        return expr.to_pyarrow().to_pylist()

    def _page(self, expr: ibis.Table, order: list, offset: int, limit: int) -> tuple[list[dict[str, Any]], int]:
        """Execute one page of an Ibis expression, with the total count.

        :param expr: The filtered expression.
        :param order: Sort keys.
        :param offset: Index of the first row.
        :param limit: Page size.
        :returns: The page's rows and the total number of rows.
        """
        check_page(offset, limit)
        total = expr.count().to_pyarrow().as_py()
        rows = self._rows(expr.order_by(order).limit(limit, offset=offset))
        return rows, total

    def _write(self, sql: str, params: list[Any] | None = None) -> None:
        """Run one write statement on the catalog.

        :param sql: The statement.
        :param params: Its parameters.
        """
        self._cat.execute(sql, params or [])

    # --- versioned definitions ---------------------------------------------------------------

    @staticmethod
    def _definition(row: dict[str, Any]) -> DefinitionVersion:
        """Build a definition record from a catalog row.

        :param row: The row.
        :returns: The record.
        """
        return DefinitionVersion(kind=row["kind"], key=row["key"], version=row["version"],
                                 body=_unjson(row["body"]), content_hash=row["content_hash"], actor=row["actor"],
                                 channel=row["channel"], created_at=_utc(row["created_at"]))

    def save_definition(self, kind: str, key: str, body: dict[str, Any],
                        context: CallContext) -> tuple[DefinitionVersion, bool]:
        """Publish a new version of a definition unless its content is unchanged (VER-1, VER-2).

        :param kind: The definition kind.
        :param key: The definition's id within its kind.
        :param body: The content as JSON-compatible data.
        :param context: Who is publishing, through which channel.
        :returns: The latest version and whether this call created it.
        """
        digest = content_hash(body)
        versions = self.list_definition_versions(kind, key)
        if versions and versions[-1].content_hash == digest:
            return versions[-1], False
        record = DefinitionVersion(kind=kind, key=key, version=len(versions) + 1, body=body, content_hash=digest,
                                   actor=context.actor, channel=context.channel, created_at=utc_now())
        self._write("INSERT INTO definitions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [kind, key, record.version, _json(body), digest, record.actor, record.channel.value,
                     _db_ts(record.created_at)])
        return record, True

    def get_definition(self, kind: str, key: str, version: int | None = None) -> DefinitionVersion:
        """Read one version of a definition (the latest when ``version`` is omitted).

        :param kind: The definition kind.
        :param key: The definition's id.
        :param version: The version.
        :returns: The definition version.
        """
        versions = self.list_definition_versions(kind, key)
        if not versions:
            raise NotFoundError(f"no {kind} named {key!r}")
        if version is None:
            return versions[-1]
        for v in versions:
            if v.version == version:
                return v
        raise NotFoundError(f"{kind} {key!r} has no version {version} (latest: {versions[-1].version})")

    def list_definitions(self, kind: str) -> list[DefinitionVersion]:
        """The latest version of every definition of a kind, ordered by key.

        :param kind: The definition kind.
        :returns: The latest versions.
        """
        t = self._ibis.table("definitions")
        t = t.filter(t.kind == kind)
        latest = t.group_by("key").aggregate(version=t.version.max())
        expr = t.semi_join(latest, ["key", "version"]).order_by("key")
        return [self._definition(r) for r in self._rows(expr)]

    def list_definition_versions(self, kind: str, key: str) -> list[DefinitionVersion]:
        """Every version of one definition, oldest first.

        :param kind: The definition kind.
        :param key: The definition's id.
        :returns: The versions.
        """
        t = self._ibis.table("definitions")
        expr = t.filter((t.kind == kind) & (t.key == key)).order_by("version")
        return [self._definition(r) for r in self._rows(expr)]

    # --- imports -----------------------------------------------------------------------------

    def _import(self, row: dict[str, Any], files: list[ImportFile]) -> DataImport:
        """Build an import record from catalog rows.

        :param row: The import's row.
        :param files: Its files.
        :returns: The record.
        """
        return DataImport(
            import_id=row["import_id"], underlying=row["underlying"], data_source=row["data_source"],
            status=row["status"], files=files, rows=row["rows"], first_as_of_date=row["first_as_of_date"],
            last_as_of_date=row["last_as_of_date"], quality_report=_unjson(row["quality_report"]),
            commit_choice=row["commit_choice"], error=row["error"], actor=row["actor"], channel=row["channel"],
            created_at=_utc(row["created_at"]), committed_at=_utc(row["committed_at"]))

    def _files_of(self, import_ids: list[str]) -> dict[str, list[ImportFile]]:
        """The files of several imports, in their recorded order.

        :param import_ids: The imports.
        :returns: Each import's files.
        """
        result: dict[str, list[ImportFile]] = {i: [] for i in import_ids}
        if not import_ids:
            return result
        t = self._ibis.table("import_files")
        for r in self._rows(t.filter(t.import_id.isin(import_ids)).order_by(["import_id", "position"])):
            result[r["import_id"]].append(ImportFile(name=r["name"], size_bytes=r["size_bytes"], sha256=r["sha256"]))
        return result

    def create_import(self, record: DataImport) -> None:
        """Record a new import with its files, in one transaction.

        :param record: The import.
        """
        self._cat.execute("BEGIN TRANSACTION")
        try:
            self._write("INSERT INTO imports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
                record.import_id, record.underlying, record.data_source, record.status.value, record.rows,
                record.first_as_of_date, record.last_as_of_date, _json(record.quality_report),
                record.commit_choice, record.error, record.actor, record.channel.value,
                _db_ts(record.created_at), _db_ts(record.committed_at)])
            for position, f in enumerate(record.files):
                self._write("INSERT INTO import_files VALUES (?, ?, ?, ?, ?)",
                            [record.import_id, position, f.name, f.size_bytes, f.sha256])
            self._cat.execute("COMMIT")
        except Exception:
            self._cat.execute("ROLLBACK")
            raise

    def update_import(self, record: DataImport) -> None:
        """Replace an import's mutable fields.

        :param record: The import with its new values.
        """
        self.get_import(record.import_id)
        self._write("""UPDATE imports SET underlying = ?, status = ?, rows = ?, first_as_of_date = ?, last_as_of_date = ?,
                       quality_report = ?, commit_choice = ?, error = ?, committed_at = ? WHERE import_id = ?""", [
            record.underlying, record.status.value, record.rows, record.first_as_of_date, record.last_as_of_date,
            _json(record.quality_report), record.commit_choice, record.error, _db_ts(record.committed_at),
            record.import_id])

    def get_import(self, import_id: str) -> DataImport:
        """Read one import.

        :param import_id: The import's id.
        :returns: The import.
        """
        t = self._ibis.table("imports")
        rows = self._rows(t.filter(t.import_id == import_id))
        if not rows:
            raise NotFoundError(f"no import {import_id!r}")
        return self._import(rows[0], self._files_of([import_id])[import_id])

    def page_imports(self, offset: int = 0, limit: int = 50, underlying: str | None = None) -> Page[DataImport]:
        """List imports, newest first.

        :param offset: Index of the first import to return.
        :param limit: Page size.
        :param underlying: Only imports of this underlying, when given.
        :returns: A page of imports.
        """
        t = self._ibis.table("imports")
        if underlying is not None:
            t = t.filter(t.underlying == underlying)
        rows, total = self._page(t, [ibis.desc("created_at"), ibis.desc("import_id")], offset, limit)
        files = self._files_of([r["import_id"] for r in rows])
        return Page[DataImport](items=[self._import(r, files[r["import_id"]]) for r in rows],
                                total=total, offset=offset, limit=limit)

    def find_imports_with_file_hash(self, sha256: str) -> list[str]:
        """Ids of imports, other than discarded ones, with a file of this hash (DATA-12).

        :param sha256: A file's SHA-256.
        :returns: The import ids, in creation order.
        """
        f = self._ibis.table("import_files")
        i = self._ibis.table("imports")
        expr = (i.filter(i.status != ImportStatus.DISCARDED.value)
                .semi_join(f.filter(f.sha256 == sha256), "import_id")
                .order_by(["created_at", "import_id"]).select("import_id"))
        return [r["import_id"] for r in self._rows(expr)]

    # --- staged market data ------------------------------------------------------------------

    def _partition_dir(self, underlying: str, year: int, month: int) -> Path:
        """The folder of one month's market files.

        :param underlying: The underlying.
        :param year: The year.
        :param month: The month.
        :returns: The folder path.
        """
        return self._home / MARKET_DIR / f"underlying={underlying}" / f"year={year:04d}" / f"month={month:02d}"

    def _import_files(self, import_id: str) -> list[Path]:
        """Every market file of an import, in path order.

        :param import_id: The import.
        :returns: The file paths.
        """
        return sorted((self._home / MARKET_DIR).glob(f"underlying=*/year=*/month=*/{import_id}.parquet"))

    @_locked
    def write_market_partition(self, import_id: str, underlying: str, year: int, month: int, table: pa.Table) -> None:
        """Write one month of an import's market snapshots to its own Parquet file.

        :param import_id: The import the rows belong to.
        :param underlying: Their underlying.
        :param year: The partition's year.
        :param month: The partition's month.
        :param table: The rows, sorted by as-of time.
        """
        folder = self._partition_dir(underlying, year, month)
        target = folder / f"{import_id}.parquet"
        if target.exists():
            raise ImmutableEntityError(f"import {import_id} already has market data for {year}-{month:02d}")
        folder.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(".parquet.partial")
        pq.write_table(table, partial, row_group_size=ROW_GROUP_SIZE, compression="zstd")
        os.replace(partial, target)

    @_locked
    def record_staged_versions(self, versions: list[DataVersionRecord]) -> None:
        """Record data versions in state ``staged``, in one transaction.

        :param versions: One record per as-of time.
        """
        self._cat.execute("BEGIN TRANSACTION")
        try:
            for v in versions:
                self._write("INSERT INTO data_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
                    v.underlying, _db_ts(v.as_of), v.as_of_date, v.import_id, VersionState.STAGED.value,
                    v.contracts, _json(v.quality_flags), _db_ts(v.state_changed_at)])
            self._cat.execute("COMMIT")
        except Exception:
            self._cat.execute("ROLLBACK")
            raise

    def list_versions(self, underlying: str, import_id: str | None = None,
                      states: list[VersionState] | None = None) -> list[DataVersionRecord]:
        """Data versions of an underlying, ordered by as-of time, then import.

        :param underlying: The underlying.
        :param import_id: Only this import's versions, when given.
        :param states: Only versions in these states, when given.
        :returns: The versions.
        """
        t = self._ibis.table("data_versions")
        t = t.filter(t.underlying == underlying)
        if import_id is not None:
            t = t.filter(t.import_id == import_id)
        if states is not None:
            t = t.filter(t.state.isin([VersionState(s).value for s in states]))
        return [DataVersionRecord(underlying=r["underlying"], as_of=_utc(r["as_of"]), as_of_date=r["as_of_date"],
                                  import_id=r["import_id"], state=r["state"], contracts=r["contracts"],
                                  quality_flags=_unjson(r["quality_flags"]),
                                  state_changed_at=_utc(r["state_changed_at"]))
                for r in self._rows(t.order_by(["as_of", "import_id"]))]

    @_locked
    def read_import_snapshot(self, import_id: str, as_of_date: date, columns: list[str] | None = None) -> pa.Table:
        """Read one date's snapshot as an import supplied it, whatever its state.

        :param import_id: The import.
        :param as_of_date: The snapshot date.
        :param columns: The columns to return; all when omitted.
        :returns: The rows, in stored order.
        """
        files = [f for f in self._import_files(import_id)
                 if f.parent.name == f"month={as_of_date.month:02d}" and f.parent.parent.name == f"year={as_of_date.year:04d}"]
        if not files:
            return pa.table({})
        # Read by path only: the folder names are layout, not columns (plan §15.3).
        t = self._ibis.read_parquet([str(f) for f in files], hive_partitioning=False)
        expr = t.filter(t.as_of_date == as_of_date)
        if columns is not None:
            expr = expr.select(columns)
        return expr.to_pyarrow()

    def _version_reads(self, underlying: str, versions: list[DataVersionRecord]) -> list[ibis.Table]:
        """One filtered read per import: its files holding these versions, restricted to their as-of times.

        Each file belongs to one import, so filtering an import's files by as-of time selects exactly
        that import's versions, whatever their state.

        :param underlying: The underlying.
        :param versions: The versions.
        :returns: The reads, in import order.
        :raises NotFoundError: If a version's file no longer exists.
        """
        by_import: dict[str, list[DataVersionRecord]] = {}
        for v in versions:
            by_import.setdefault(v.import_id, []).append(v)
        reads = []
        for import_id in sorted(by_import):
            group = by_import[import_id]
            files = sorted({self._partition_dir(underlying, v.as_of_date.year, v.as_of_date.month) / f"{import_id}.parquet"
                            for v in group})
            gone = [f for f in files if not f.exists()]
            if gone:
                raise NotFoundError(f"market data of import {import_id} is no longer stored ({gone[0].parent.name}, "
                                    f"{gone[0].parent.parent.name}): it was purged")
            # Read by path only: the folder names are layout, not columns (plan §15.3).
            t = self._ibis.read_parquet([str(f) for f in files], hive_partitioning=False)
            reads.append(t.filter(t.as_of.isin([v.as_of for v in group])))
        return reads

    @_locked
    def read_market_chunk(self, underlying: str, versions: list[DataVersionRecord], columns: list[str] | None = None,
                          max_days_to_expiry: float | None = None) -> pa.Table:
        """Read the rows of exactly these data versions, whatever their state now (plan §4.6, decision 30).

        :param underlying: The underlying.
        :param versions: The versions to read, one per as-of time.
        :param columns: The columns to return; all when omitted.
        :param max_days_to_expiry: Only rows whose ``days_to_expiry`` is at most this; every row when omitted.
        :returns: The rows, ordered by as-of time, then root, expiration, option type and strike where present.
        :raises NotFoundError: If a version's file no longer exists (it was purged).
        """
        if not versions:
            return pa.table({})
        reads = self._version_reads(underlying, versions)
        if max_days_to_expiry is not None:
            reads = [r.filter(r.days_to_expiry <= max_days_to_expiry) for r in reads]
        order = [k for k in SORT_KEYS if k in reads[0].columns]
        if columns is not None:
            # Sort keys are read even when not asked for, then dropped, so the order is always defined.
            reads = [r.select(list(dict.fromkeys([*columns, *order]))) for r in reads]
        expr = reads[0].union(*reads[1:]) if len(reads) > 1 else reads[0]
        table = expr.order_by(order).to_pyarrow()
        return table.select(columns) if columns is not None else table

    @_locked
    def read_index_levels(self, underlying: str, versions: list[DataVersionRecord]) -> dict[datetime, float]:
        """The index level of each of these data versions' snapshots.

        :param underlying: The underlying.
        :param versions: The versions, one per as-of time.
        :returns: The index level by as-of instant (aware, UTC).
        :raises NotFoundError: If a version's file no longer exists.
        """
        if not versions:
            return {}
        reads = [r.group_by("as_of").aggregate(index_level=r.index_level.max())
                 for r in self._version_reads(underlying, versions)]
        expr = reads[0].union(*reads[1:]) if len(reads) > 1 else reads[0]
        return {row["as_of"].astimezone(timezone.utc): row["index_level"] for row in expr.to_pyarrow().to_pylist()}

    @_locked
    def discard_import(self, import_id: str) -> None:
        """Delete a staged import's files and mark it and its versions discarded.

        :param import_id: The import.
        """
        record = self.get_import(import_id)
        if record.status == ImportStatus.COMMITTED:
            raise ImmutableEntityError("only staged imports can be discarded: delete or purge instead")
        v = self._ibis.table("data_versions")
        used = self._rows(v.filter((v.import_id == import_id)
                                   & ~v.state.isin([VersionState.STAGED.value, VersionState.DISCARDED.value]))
                          .select("state").distinct())
        if used:
            raise ImmutableEntityError(
                f"import {import_id} has versions in use ({', '.join(sorted(r['state'] for r in used))}); "
                "only staged imports can be discarded: delete or purge instead")
        now = _db_ts(utc_now())
        def apply():
            self._write("UPDATE data_versions SET state = ?, state_changed_at = ? WHERE import_id = ?",
                        [VersionState.DISCARDED.value, now, import_id])
            self._write("UPDATE imports SET status = ?, commit_choice = ?, committed_at = ? WHERE import_id = ?",
                        [ImportStatus.DISCARDED.value, "cancel", now, import_id])
        self._file_transaction({path: None for path in self._import_files(import_id)}, apply)

    # --- jobs --------------------------------------------------------------------------------

    @staticmethod
    def _job(row: dict[str, Any]) -> JobRecord:
        """Build a job record from a catalog row.

        :param row: The row.
        :returns: The record.
        """
        return JobRecord(
            job_id=row["job_id"], kind=row["kind"], params=_unjson(row["params"]), status=row["status"],
            progress_done=row["progress_done"], progress_total=row["progress_total"],
            progress_label=row["progress_label"], result=_unjson(row["result"]), error=row["error"],
            cancel_requested=row["cancel_requested"], actor=row["actor"], channel=row["channel"],
            created_at=_utc(row["created_at"]), started_at=_utc(row["started_at"]),
            finished_at=_utc(row["finished_at"]))

    def insert_job(self, record: JobRecord) -> None:
        """Record a new job.

        :param record: The job.
        """
        self._write("INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            record.job_id, record.kind, _json(record.params), record.status.value, record.progress_done,
            record.progress_total, record.progress_label, _json(record.result), record.error,
            record.cancel_requested, record.actor, record.channel.value, _db_ts(record.created_at),
            _db_ts(record.started_at), _db_ts(record.finished_at)])

    def update_job(self, record: JobRecord) -> None:
        """Replace a job's mutable fields.

        :param record: The job with its new values.
        """
        self.get_job(record.job_id)
        self._write("""UPDATE jobs SET status = ?, progress_done = ?, progress_total = ?, progress_label = ?,
                       result = ?, error = ?, cancel_requested = ?, started_at = ?, finished_at = ?
                       WHERE job_id = ?""", [
            record.status.value, record.progress_done, record.progress_total, record.progress_label,
            _json(record.result), record.error, record.cancel_requested, _db_ts(record.started_at),
            _db_ts(record.finished_at), record.job_id])

    def get_job(self, job_id: str) -> JobRecord:
        """Read one job.

        :param job_id: The job's id.
        :returns: The job.
        """
        t = self._ibis.table("jobs")
        rows = self._rows(t.filter(t.job_id == job_id))
        if not rows:
            raise NotFoundError(f"no job {job_id!r}")
        return self._job(rows[0])

    def page_jobs(self, offset: int = 0, limit: int = 50, statuses: list[JobStatus] | None = None) -> Page[JobRecord]:
        """List jobs, newest first.

        :param offset: Index of the first job to return.
        :param limit: Page size.
        :param statuses: Only jobs in these statuses, when given.
        :returns: A page of jobs.
        """
        t = self._ibis.table("jobs")
        if statuses is not None:
            t = t.filter(t.status.isin([JobStatus(s).value for s in statuses]))
        rows, total = self._page(t, [ibis.desc("created_at"), ibis.desc("job_id")], offset, limit)
        return Page[JobRecord](items=[self._job(r) for r in rows], total=total, offset=offset, limit=limit)

    # --- attempts ----------------------------------------------------------------------------

    def append_attempt(self, record: AttemptRecord) -> None:
        """Record an attempt.

        :param record: The attempt.
        """
        self._write("INSERT INTO attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
            record.attempt_id, record.operation, _json(record.params_summary), record.outcome.value,
            _json(record.reasons), record.actor, record.channel.value, _db_ts(record.attempted_at)])

    def page_attempts(self, offset: int = 0, limit: int = 50, operation: str | None = None) -> Page[AttemptRecord]:
        """List attempts, newest first.

        :param offset: Index of the first attempt to return.
        :param limit: Page size.
        :param operation: Only attempts at this operation, when given.
        :returns: A page of attempts.
        """
        t = self._ibis.table("attempts")
        if operation is not None:
            t = t.filter(t.operation == operation)
        rows, total = self._page(t, [ibis.desc("attempted_at"), ibis.desc("attempt_id")], offset, limit)
        items = [AttemptRecord(attempt_id=r["attempt_id"], operation=r["operation"],
                               params_summary=_unjson(r["params_summary"]), outcome=r["outcome"],
                               reasons=_unjson(r["reasons"]), actor=r["actor"], channel=r["channel"],
                               attempted_at=_utc(r["attempted_at"]))
                 for r in rows]
        return Page[AttemptRecord](items=items, total=total, offset=offset, limit=limit)
