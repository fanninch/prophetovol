"""The ``ivolatility_eod`` ingest adapter (DATA-10 to DATA-21, DATA-15): vendor files in, staged
normalized snapshots out.

Steps, each a progress point and a cancellation point (INT-24):

1. receive the files (folders and zips expanded, every file hashed, the size limit checked)
2. check headers
3. parse; structural checks (errors stop the import here, with its quality report)
4. derive the normalized columns, forwards and internal IV; content checks
5. write one Parquet partition per month (internal greeks filled in), then record the staged versions

The work happens in a private DuckDB working database under ``<home>/uploads/<import_id>/``, removed
at the end; vendor-specific SQL stays here and storage sees only finished partitions (DATA-83).
Nothing becomes visible to runs until the import is committed (Phase 7).
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from prophetovol.core.errors import NotFoundError, ValidationFailed, ValidationIssue
from prophetovol.core.ids import new_id, utc_now
from prophetovol.core.records import DataImport, DataVersionRecord, ImportFile, ImportStatus, VersionState
from prophetovol.data import derive, validation
from prophetovol.data.quality import QualityReport
from prophetovol.data.receive import DEFAULT_MAX_IMPORT_BYTES, clean_up, plan_inputs, receive
from prophetovol.reference.calendar import TradingCalendar
from prophetovol.reference.models import DataSource, Underlying
from prophetovol.runs.jobs import JobCancelled, JobContext

UNDERLYING = "underlying"
"""Definition kind of underlying configurations."""

DATA_SOURCE = "data_source"
"""Definition kind of data-source configurations."""

DEFAULT_MEMORY_LIMIT = "2GB"
"""DuckDB memory limit of the working database; larger work spills to disk."""

FIXED_STEPS = 4
"""Progress steps before the partitions: receive, headers, parse and check, derive and check."""


def _headers(files: list[Path]) -> dict[str, tuple[str, ...]]:
    """Read each file's header row.

    :param files: The CSV files.
    :returns: Header rows by file name.
    """
    out = {}
    for f in files:
        with open(f, newline="", encoding="utf-8-sig") as handle:
            out[f.name] = tuple(next(csv.reader(handle), []))
    return out


def _refuse(record: DataImport, report: QualityReport, storage: Any) -> None:
    """Mark an import failed by validation, keep its report, and raise.

    :param record: The import.
    :param report: Its quality report.
    :param storage: The job's storage.
    :raises ValidationFailed: Always, with one issue per error check.
    """
    record.status = ImportStatus.FAILED
    record.quality_report = report.model_dump(mode="json")
    record.error = "validation failed: " + ", ".join(f"{c.name} ({c.count})" for c in report.errors)
    record.committed_at = None
    storage.update_import(record)
    raise ValidationFailed([ValidationIssue(c.name, f"{c.count} finding(s): {c.description}") for c in report.errors])


def ingest(ctx: JobContext, calendar: TradingCalendar, max_bytes: int = DEFAULT_MAX_IMPORT_BYTES,
           memory_limit: str = DEFAULT_MEMORY_LIMIT) -> dict[str, Any]:
    """Run an import job: ``ctx.params`` holds ``paths`` (files, folders, zips) and ``data_source``.

    :param ctx: The job's context (storage, progress, cancellation, who started it).
    :param calendar: The trading calendar.
    :param max_bytes: The largest total uncompressed size allowed.
    :param memory_limit: DuckDB memory limit for the working database.
    :returns: The import's id and status, and its error and warning counts.
    :raises ValidationFailed: If the inputs are refused or validation finds errors (the import is then
        recorded as failed, with its quality report).
    :raises JobCancelled: If the job is cancelled (anything written is discarded).
    """
    storage = ctx.storage
    source = DataSource.model_validate(storage.get_definition(DATA_SOURCE, ctx.params["data_source"]).body)
    items = plan_inputs([Path(p) for p in ctx.params["paths"]], max_bytes)
    import_id = new_id("imp")
    work = storage.home / "uploads" / import_id
    record: DataImport | None = None
    con = None
    try:
        ctx.progress(0, None, "receiving files")
        files = receive(items, work)
        duplicates = {f.name: storage.find_imports_with_file_hash(f.sha256) for f in files}
        record = DataImport(import_id=import_id, underlying="", data_source=source.source_id,
                            status=ImportStatus.INGESTING,
                            files=[ImportFile(name=f.name, size_bytes=f.size_bytes, sha256=f.sha256) for f in files],
                            actor=ctx.context.actor, channel=ctx.context.channel, created_at=utc_now())
        storage.create_import(record)
        ctx.record.result = {"import_id": import_id}  # retain the report link even when validation fails
        ctx.check_cancelled()

        ctx.progress(1, None, "checking headers")
        header = validation.header_check(_headers([f.path for f in files]))
        if header.count:
            _refuse(record, QualityReport(rows=0, dates=0, checks=[header]), storage)
        ctx.check_cancelled()

        ctx.progress(2, None, "parsing")
        con = derive.open_work_db(work / "work.duckdb", memory_limit)
        rows = derive.load_files(con, [f.path for f in files])
        symbols = [s for (s,) in con.execute("SELECT DISTINCT symbol FROM p").fetchall()]
        known = {d.key for d in storage.list_definitions(UNDERLYING)}
        underlying = None
        if len(symbols) == 1 and symbols[0] in known:
            underlying = Underlying.model_validate(storage.get_definition(UNDERLYING, symbols[0]).body)
            record.underlying = underlying.symbol
        sessions = derive.load_reference(con, underlying, calendar)
        first, last, ndates = con.execute("SELECT min(dt), max(dt), count(DISTINCT dt) FROM p").fetchone()
        record.rows, record.first_as_of_date, record.last_as_of_date = rows, first, last
        checks = validation.structural_checks(con, known, duplicates)
        report = QualityReport(rows=rows, dates=ndates, first_as_of_date=first, last_as_of_date=last, checks=checks)
        if report.errors or underlying is None:
            _refuse(record, report, storage)
        ctx.check_cancelled()

        ctx.progress(3, None, "deriving columns")
        derive.derive(con, underlying, source)
        report.checks += validation.content_checks(con, sessions)
        record.quality_report = report.model_dump(mode="json")
        storage.update_import(record)
        ctx.check_cancelled()

        months = derive.partitions(con)
        total = FIXED_STEPS + len(months)
        for i, (year, month) in enumerate(months):
            ctx.check_cancelled()
            ctx.progress(FIXED_STEPS + i, total, f"writing {year}-{month:02d}")
            table = derive.read_partition(con, year, month, import_id, source.internal_greeks_from)
            storage.write_market_partition(import_id, underlying.symbol, year, month, table)
        ctx.check_cancelled()

        storage.record_staged_versions(_versions(con, record, report, source))
        record.status = ImportStatus.STAGED
        storage.update_import(record)
        ctx.progress(total, total, "staged")
        return {"import_id": import_id, "status": record.status.value, "rows": rows,
                "errors": len(report.errors), "warnings": len(report.warnings)}
    except (JobCancelled, KeyboardInterrupt):
        if record is not None:
            storage.discard_import(import_id)
            discarded = storage.get_import(import_id)
            discarded.error = "cancelled during ingest"
            storage.update_import(discarded)
        raise
    except ValidationFailed:
        raise
    except Exception as exc:
        if record is not None:
            record.status, record.error = ImportStatus.FAILED, str(exc) or type(exc).__name__
            try:
                storage.update_import(record)
            except NotFoundError:
                pass
        raise
    finally:
        if con is not None:
            con.close()
        clean_up(work)


def _versions(con: Any, record: DataImport, report: QualityReport, source: DataSource) -> list[DataVersionRecord]:
    """One staged data version per snapshot date of the import.

    :param con: The working database, with table ``n``.
    :param record: The import.
    :param report: Its quality report (for each date's flags).
    :param source: The data source (for the as-of time).
    :returns: The version records.
    """
    flags = report.flags_by_date()
    tz = ZoneInfo(source.timezone)
    now = utc_now()
    out = []
    for day, contracts in con.execute("SELECT as_of_date, count(*) FROM n GROUP BY 1 ORDER BY 1").fetchall():
        as_of = datetime.combine(day, source.option_snapshot_time, tzinfo=tz)
        out.append(DataVersionRecord(underlying=record.underlying, as_of=as_of, as_of_date=day,
                                     import_id=record.import_id, state=VersionState.STAGED, contracts=contracts,
                                     quality_flags=flags.get(day, []), state_changed_at=now))
    return out


def quality_report(record: DataImport) -> QualityReport | None:
    """The quality report stored with an import.

    :param record: The import.
    :returns: The report, or ``None`` if validation has not run.
    """
    return None if record.quality_report is None else QualityReport.model_validate(record.quality_report)

