"""``BacktestService``: the single owner of all storage access (ARC-1).

The CLI, the API and later an agent call only this service. One process opens a home directory
at a time (INT-41); inside it, one owning service holds the databases and request threads use
:meth:`BacktestService.reader` (ARC-4).
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from types import TracebackType
from typing import Any

import pyarrow as pa
import pydantic

from prophetovol.core.context import CallContext, Channel
from prophetovol.core.errors import ConfigurationError, ImmutableEntityError, ValidationFailed, ValidationIssue
from prophetovol.core.home import resolve_home
from prophetovol.core.paging import Page
from prophetovol.core.records import (AttemptRecord, DataImport, DataVersionRecord, DefinitionVersion, JobRecord,
                                      JobStatus, VersionState)
from prophetovol.data import ingest as ingest_module
from prophetovol.data.lifecycle import (ChangePreview, CommitChoice, CoverageDay, CoverageMonth, CoverageReport,
                                        DataSelection, OverlapItem, RunImpact)
from prophetovol.data.quality import QualityReport
from prophetovol.data.receive import DEFAULT_MAX_IMPORT_BYTES, plan_inputs
from prophetovol.reference.calendar import TradingCalendar, nyse_calendar
from prophetovol.reference.defaults import default_data_sources, default_underlyings
from prophetovol.reference.models import DataSource, Underlying
from prophetovol.registry.mechanism import ImplementationInfo, RegistryInfo
from prophetovol.runs.audit import audited
from prophetovol.runs.jobs import JobContext, JobHandler, JobRunner, execute_job, new_job, recover_interrupted_jobs
from prophetovol.storage.adapter import StorageAdapter
from prophetovol.storage.duckdb.adapter import DuckDBAdapter

UNDERLYING = "underlying"
"""Definition kind of underlying configurations (REF-1, REF-2)."""

DATA_SOURCE = "data_source"
"""Definition kind of data-source configurations (REF-5)."""


class BacktestService:
    """Every ProphetoVol capability, over one home directory.

    Create the owning service with :meth:`open`; it can be used as a context manager.

    :param storage: The storage adapter.
    :param calendar: The trading calendar.
    :param owner: Whether this service owns the storage (only the owner seeds reference data).
    """

    def __init__(self, storage: StorageAdapter, calendar: TradingCalendar, owner: bool) -> None:
        self.storage = storage
        self.calendar = calendar
        self._owner = owner
        self._runner: JobRunner | None = None
        self.recovered_jobs: list[str] = []
        self.max_import_bytes = DEFAULT_MAX_IMPORT_BYTES
        self.ingest_memory_limit = ingest_module.DEFAULT_MEMORY_LIMIT

    @classmethod
    def open(cls, home: str | os.PathLike[str] | None = None,
             context: CallContext | None = None) -> BacktestService:
        """Open a home directory, creating and migrating it if needed, and seed the shipped reference data.

        :param home: The home directory; resolved by :func:`~prophetovol.core.home.resolve_home` when omitted.
        :param context: Who is opening, through which channel; recorded on seeded definitions.
            Defaults to the current user through the library channel.
        :returns: The owning service.
        :raises HomeLockedError: If another process has the home directory open.
        """
        storage = DuckDBAdapter.open(resolve_home(home))
        service = cls(storage, nyse_calendar(), owner=True)
        try:
            service._seed_reference_data(context or CallContext.for_channel(Channel.LIBRARY))
            service.recovered_jobs = recover_interrupted_jobs(storage)
        except Exception:
            storage.close()
            raise
        return service

    def _seed_reference_data(self, context: CallContext) -> None:
        """Publish the shipped underlyings and data sources as version 1 where none exist yet.

        Definitions already in the catalog are left alone, so changes made through the service
        (REF-2) are never overwritten by the shipped defaults.

        :param context: Who is opening the home directory.
        """
        for kind, defaults in ((UNDERLYING, default_underlyings()), (DATA_SOURCE, default_data_sources())):
            existing = {d.key for d in self.storage.list_definitions(kind)}
            for key, model in defaults.items():
                if key not in existing:
                    self.storage.save_definition(kind, key, model.model_dump(mode="json"), context)

    @property
    def home(self) -> Path:
        """The home directory."""
        return self.storage.home

    def reader(self) -> BacktestService:
        """A service on independent cursors of the same databases, for a request thread (ARC-4).

        :returns: The reader service; closing it leaves the owner open.
        """
        return BacktestService(self.storage.reader(), self.calendar, owner=False)

    def close(self) -> None:
        """Stop the job runner, if started, and close the service and its storage."""
        self.stop_jobs()
        self.storage.close()

    def __enter__(self) -> BacktestService:
        """Return the service itself, for ``with`` blocks."""
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        """Close the service at the end of a ``with`` block.

        :param exc_type: The exception type, if one was raised.
        :param exc: The exception, if one was raised.
        :param tb: Its traceback.
        """
        self.close()

    # --- reference data (§7) -----------------------------------------------------------------

    def underlying(self, symbol: str, version: int | None = None) -> Underlying:
        """An underlying's configuration.

        :param symbol: The underlying, for example ``SPX``.
        :param version: The version; the latest when omitted.
        :returns: The configuration.
        :raises NotFoundError: If it does not exist.
        """
        return Underlying.model_validate(self.storage.get_definition(UNDERLYING, symbol, version).body)

    def list_underlyings(self) -> list[str]:
        """The configured underlyings, in alphabetical order.

        :returns: Their symbols.
        """
        return [d.key for d in self.storage.list_definitions(UNDERLYING)]

    def data_source(self, source_id: str, version: int | None = None) -> DataSource:
        """A data source's configuration.

        :param source_id: The data source, for example ``ivolatility_eod``.
        :param version: The version; the latest when omitted.
        :returns: The configuration.
        :raises NotFoundError: If it does not exist.
        """
        return DataSource.model_validate(self.storage.get_definition(DATA_SOURCE, source_id, version).body)

    def list_data_sources(self) -> list[str]:
        """The configured data sources, in alphabetical order.

        :returns: Their ids.
        """
        return [d.key for d in self.storage.list_definitions(DATA_SOURCE)]

    @audited("reference.publish_underlying")
    def publish_underlying(self, body: dict[str, Any], context: CallContext) -> tuple[DefinitionVersion, bool]:
        """Validate and publish a new version of an underlying's configuration (REF-2, VER-1).

        :param body: The configuration, as in ``reference/defaults/underlyings``.
        :param context: Who is publishing, through which channel.
        :returns: The latest version and whether this call created it (unchanged content publishes nothing).
        :raises ValidationFailed: If the configuration is invalid; every issue has its field path.
        """
        try:
            model = Underlying.model_validate(body)
        except pydantic.ValidationError as exc:
            raise ValidationFailed.from_pydantic(exc) from None
        return self.storage.save_definition(UNDERLYING, model.symbol, model.model_dump(mode="json"), context)

    @audited("reference.publish_data_source")
    def publish_data_source(self, body: dict[str, Any], context: CallContext) -> tuple[DefinitionVersion, bool]:
        """Validate and publish a new version of a data source's configuration (REF-5, VER-1).

        :param body: The configuration, as in ``reference/defaults/data_sources``.
        :param context: Who is publishing, through which channel.
        :returns: The latest version and whether this call created it.
        :raises ValidationFailed: If the configuration is invalid.
        """
        try:
            model = DataSource.model_validate(body)
        except pydantic.ValidationError as exc:
            raise ValidationFailed.from_pydantic(exc) from None
        return self.storage.save_definition(DATA_SOURCE, model.source_id, model.model_dump(mode="json"), context)

    # --- jobs (§13.3) ------------------------------------------------------------------------

    def start_jobs(self, handlers: dict[str, JobHandler]) -> None:
        """Start the background job runner (the server does this; the CLI runs jobs in the foreground).

        :param handlers: The handler for each job kind.
        :raises ConfigurationError: On a reader service, or if the runner is already running.
        """
        if not self._owner:
            raise ConfigurationError("only the owning service runs jobs")
        if self._runner is not None:
            raise ConfigurationError("the job runner is already running")
        self._runner = JobRunner(self.storage, handlers)
        self._runner.start()

    def stop_jobs(self, timeout: float | None = None) -> None:
        """Stop the job runner after its current job; queued jobs are cancelled. Does nothing if not started.

        :param timeout: Seconds to wait for the current job; as long as it takes when omitted.
        """
        if self._runner is not None:
            self._runner.stop(timeout)
            self._runner = None

    @property
    def jobs(self) -> JobRunner:
        """The running job runner; raises ``ConfigurationError`` if it has not been started."""
        if self._runner is None:
            raise ConfigurationError("the job runner is not running")
        return self._runner

    def submit_job(self, kind: str, params: dict[str, Any], context: CallContext) -> JobRecord:
        """Queue a job on the background runner (INT-20); it returns at once.

        Operations that start jobs are audited themselves, so this plumbing is not.

        :param kind: What the job does.
        :param params: Its parameters.
        :param context: Who is starting it.
        :returns: The queued job.
        """
        return self.jobs.submit(kind, params, context)

    def run_job(self, kind: str, params: dict[str, Any], handler: JobHandler, context: CallContext) -> JobRecord:
        """Run a job in the calling thread, recording it like a background job (the CLI's way, plan §4.8).

        :param kind: What the job does.
        :param params: Its parameters.
        :param handler: The job's work.
        :param context: Who is starting it.
        :returns: The finished job.
        """
        record = new_job(kind, params, context)
        self.storage.insert_job(record)
        return execute_job(record, handler, self.storage)

    @audited("jobs.cancel")
    def cancel_job(self, job_id: str, context: CallContext) -> JobRecord:
        """Cancel a queued or running job (INT-24).

        :param job_id: The job.
        :param context: Who is cancelling it.
        :returns: The job after the request.
        :raises NotFoundError: If the job does not exist.
        :raises ImmutableEntityError: If it has already finished.
        """
        if self._runner is None:
            job = self.storage.get_job(job_id)
            if job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
                raise ImmutableEntityError(f"job {job_id} has already finished ({job.status})")
            raise ConfigurationError("this service has no running job worker; cancel through the owning service")
        return self.jobs.cancel(job_id)

    def get_job(self, job_id: str) -> JobRecord:
        """Read one job.

        :param job_id: The job.
        :returns: The job.
        """
        return self.storage.get_job(job_id)

    def page_jobs(self, offset: int = 0, limit: int = 50, statuses: list[JobStatus] | None = None) -> Page[JobRecord]:
        """List jobs, newest first.

        :param offset: Index of the first job to return.
        :param limit: Page size.
        :param statuses: Only jobs in these statuses, when given.
        :returns: A page of jobs.
        """
        return self.storage.page_jobs(offset, limit, statuses)

    # --- audit (§15) -------------------------------------------------------------------------

    def page_attempts(self, offset: int = 0, limit: int = 50, operation: str | None = None) -> Page[AttemptRecord]:
        """List attempts, newest first (AUD-2).

        :param offset: Index of the first attempt to return.
        :param limit: Page size.
        :param operation: Only attempts at this operation, when given.
        :returns: A page of attempts.
        """
        return self.storage.page_attempts(offset, limit, operation)

    # --- data (§6) ---------------------------------------------------------------------------

    def job_handlers(self) -> dict[str, JobHandler]:
        """The handler of every job kind this service runs, for :meth:`start_jobs`.

        :returns: Handlers by job kind.
        """
        return {"ingest": self._ingest_job, "commit": self._data_job, "delete": self._data_job, "purge": self._data_job}

    def _ingest_job(self, ctx: JobContext) -> dict[str, Any]:
        """Run an import job (the ``ingest`` job kind).

        :param ctx: The job's context.
        :returns: The import's id, status and counts.
        """
        return ingest_module.ingest(ctx, self.calendar, self.max_import_bytes, self.ingest_memory_limit)

    @audited("data.import")
    def import_files(self, paths: list[str | os.PathLike[str]], context: CallContext,
                     data_source: str = "ivolatility_eod", background: bool = False) -> JobRecord:
        """Import vendor files: one or more CSV files, folders of them, or zip archives, as one import (DATA-3, DATA-4).

        The files are validated, normalized and staged (DATA-10 to DATA-21); nothing becomes visible to runs
        until the import is committed. The inputs are checked before any job starts, so a missing file or an
        import over the size limit is refused at once.

        :param paths: The files, folders and archives.
        :param context: Who is importing, through which channel.
        :param data_source: The data source the files are in.
        :param background: Queue the import on the job runner and return at once (the server's way); otherwise
            run it in the calling thread (the CLI's way).
        :returns: The job; when it has finished, its result holds the ``import_id``.
        :raises ValidationFailed: If an input is missing or unsupported, or the import is too large.
        :raises NotFoundError: If the data source is not configured.
        """
        resolved = [str(Path(p).resolve()) for p in paths]
        plan_inputs([Path(p) for p in resolved], self.max_import_bytes)
        self.data_source(data_source)
        params = {"paths": resolved, "data_source": data_source}
        if background:
            return self.submit_job("ingest", params, context)
        return self.run_job("ingest", params, self._ingest_job, context)

    def get_import(self, import_id: str) -> DataImport:
        """Read one import.

        :param import_id: The import.
        :returns: The import.
        :raises NotFoundError: If it does not exist.
        """
        return self.storage.get_import(import_id)

    def page_imports(self, offset: int = 0, limit: int = 50, underlying: str | None = None) -> Page[DataImport]:
        """List imports, newest first.

        :param offset: Index of the first import to return.
        :param limit: Page size.
        :param underlying: Only imports of this underlying, when given.
        :returns: A page of imports.
        """
        return self.storage.page_imports(offset, limit, underlying)

    def quality_report(self, import_id: str) -> QualityReport | None:
        """An import's quality report (DATA-21).

        :param import_id: The import.
        :returns: The report, or ``None`` if validation has not run.
        :raises NotFoundError: If the import does not exist.
        """
        return ingest_module.quality_report(self.storage.get_import(import_id))

    def _data_job(self, ctx: JobContext) -> dict[str, Any]:
        """Execute lifecycle work with the worker's cursor and an execution audit record."""
        service = BacktestService(ctx.storage, self.calendar, owner=False)
        ctx.check_cancelled()
        ctx.progress(0, 1, ctx.record.kind)
        result = service._execute_data(ctx.record.kind, ctx.params, ctx.record.job_id, ctx.context, ctx)
        ctx.progress(1, 1, "complete")
        return result

    @audited("data.execute")
    def _execute_data(self, operation: str, params: dict[str, Any], job_id: str,
                      context: CallContext, ctx: JobContext) -> dict[str, Any]:
        """Audit execution separately from submission, including failures and stale confirmations."""
        if operation == "commit":
            count = self.storage.commit_import(params["import_id"], CommitChoice(params["choice"]))
            return {"import_id": params["import_id"], "activated": count}
        preview = ChangePreview.model_validate(params["preview"])
        count = self.storage.apply_change(preview, progress=lambda done, total: self._file_progress(ctx, done, total))
        return {"operation": operation, "versions": count, "confirmation": preview.token}

    def _file_progress(self, ctx: JobContext, done: int, total: int) -> None:
        """Check cancellation between purge files and persist progress."""
        ctx.check_cancelled()
        if done < total / 2:
            ctx.progress(done, total, "preparing purge")
        else:
            # The replacement phase holds a catalog transaction. Do not write the job row here:
            # a concurrent cancel request must be able to update it without a write conflict.
            ctx.record.progress_done = done
            ctx.record.progress_total = total
            ctx.record.progress_label = "purging files"

    def _start_data_job(self, kind, params, context, background):
        """Dispatch lifecycle operations through the existing job machinery."""
        if background:
            return self.submit_job(kind, params, context)
        return self.run_job(kind, params, self._data_job, context)

    @audited("data.overlap")
    def overlap(self, import_id: str, context: CallContext) -> list[OverlapItem]:
        """Show staged snapshots and their active overlaps before commit.

        :param import_id: Staged import to review.
        :param context: Who is reviewing the import.
        :returns: Incoming and existing snapshots, with imports and counts.
        """
        return self.storage.overlap(import_id)

    @audited("data.commit")
    def commit_import(self, import_id: str, choice: CommitChoice, context: CallContext,
                      background: bool = False) -> JobRecord:
        """Commit or discard reviewed staged data as a persisted job.

        :param import_id: Staged import.
        :param choice: ``replace``, ``add_new`` or ``cancel``.
        :param context: Who chose the operation.
        :param background: Queue on the running worker instead of executing immediately.
        :returns: Job with the activation count or error.
        """
        try:
            choice = CommitChoice(choice)
        except ValueError:
            raise ValidationFailed([ValidationIssue("choice", "choose replace, add_new or cancel")]) from None
        self.storage.overlap(import_id)
        return self._start_data_job("commit", {"import_id": import_id, "choice": choice.value}, context, background)

    @audited("data.preview")
    def preview_data_change(self, operation: str, selection: DataSelection,
                            context: CallContext) -> ChangePreview:
        """Preview eligible data and affected runs before a delete or purge.

        :param operation: ``delete`` or ``purge``.
        :param selection: An import to purge, or an inclusive underlying/date range.
        :param context: Who requested the preview.
        :returns: Report to present for confirmation; reuse it when submitting the operation.
        """
        return self.storage.preview_change(operation, selection)

    def _confirmed_change(self, operation, preview, confirmed, context, background):
        """Validate an explicit confirmation and submit the exact reviewed scope."""
        if not confirmed or preview.operation != operation:
            raise ValidationFailed([ValidationIssue("confirmation", "review the affected runs and confirm this operation")])
        current = self.storage.preview_change(operation, preview.selection)
        if current.token != preview.token:
            raise ValidationFailed([ValidationIssue("confirmation", "data or affected runs changed; review and confirm again")])
        return self._start_data_job(operation, {"preview": preview.model_dump(mode="json")}, context, background)

    @audited("data.delete")
    def delete_data(self, preview: ChangePreview, context: CallContext, confirmed: bool = False,
                    background: bool = False) -> JobRecord:
        """Deactivate active versions after confirmation, keeping their files and run results.

        :param preview: Previously reviewed delete report.
        :param context: Who confirmed the deletion.
        :param confirmed: Explicit confirmation; defaults to refusal.
        :param background: Queue the job instead of executing immediately.
        :returns: Job with the count of deactivated versions.
        """
        return self._confirmed_change("delete", preview, confirmed, context, background)

    @audited("data.purge")
    def purge_data(self, preview: ChangePreview, context: CallContext, confirmed: bool = False,
                   background: bool = False) -> JobRecord:
        """Physically remove reviewed superseded/deleted data, retaining audit and results.

        :param preview: Previously reviewed purge report.
        :param context: Who confirmed the purge.
        :param confirmed: Explicit confirmation; defaults to refusal.
        :param background: Queue the job instead of executing immediately.
        :returns: Job with the count of purged versions.
        """
        return self._confirmed_change("purge", preview, confirmed, context, background)

    def run_data_impacts(self, run_id: str) -> list[RunImpact]:
        """Read a run's persisted data-superseded dates.

        :param run_id: The run id.
        :returns: Affected dates grouped by underlying.
        """
        return self.storage.run_data_impacts(run_id)

    @audited("data.coverage")
    def coverage(self, underlying: str, start: date, end: date, context: CallContext) -> CoverageReport:
        """Report trading-day coverage and monthly counts over an inclusive date range.

        :param underlying: Configured underlying.
        :param start: First date, inclusive.
        :param end: Last date, inclusive.
        :param context: Who requested the report.
        :returns: Every trading day plus non-trading dates with data, and monthly summaries.
        """
        self.underlying(underlying)
        if start > end:
            raise ValidationFailed([ValidationIssue("end", "end must be on or after start")])
        sessions = set(self.calendar.sessions_in_range(start, end))
        by_day = {}
        for v in self.storage.list_versions(underlying, states=[VersionState.ACTIVE]):
            if start <= v.as_of_date <= end:
                by_day.setdefault(v.as_of_date, []).append(v)
        days = [CoverageDay(day=d, trading_day=d in sessions, snapshots=by_day.get(d, []))
                for d in sorted(sessions | set(by_day))]
        groups = {}
        for d in days:
            groups.setdefault(d.day.strftime("%Y-%m"), []).append(d)
        months = []
        for month, entries in sorted(groups.items()):
            trading = sum(d.trading_day for d in entries)
            covered = sum(d.trading_day and bool(d.snapshots) for d in entries)
            months.append(CoverageMonth(month=month, trading_days=trading, covered_days=covered,
                missing_days=trading-covered, non_trading_days=sum(not d.trading_day for d in entries),
                contracts=sum(v.contracts for d in entries for v in d.snapshots),
                flagged_days=sum(any(v.quality_flags for v in d.snapshots) for d in entries)))
        return CoverageReport(underlying=underlying, days=days, months=months)

    def list_registries(self) -> list[RegistryInfo]:
        """Describe all registered component types (REG-3).

        :returns: Registry metadata in name order.
        """
        from prophetovol.registry.catalog import all_registries
        return [registry.info() for registry in all_registries()]

    @audited("registry.list")
    def list_implementations(self, kind: str, context: CallContext) -> list[ImplementationInfo]:
        """Describe a registry's implementations and parameter schemas.

        :param kind: Registry type, such as settlement_source.
        :param context: Who requested discovery.
        :returns: Implementation metadata in name order.
        """
        from prophetovol.registry.catalog import get_registry
        registry = get_registry(kind)
        return [registry.describe(name) for name in registry.names()]

    @audited("registry.show")
    def describe_implementation(self, kind: str, name: str, context: CallContext) -> ImplementationInfo:
        """Describe a named implementation, including its JSON Schema.

        :param kind: Registry type.
        :param name: Implementation name.
        :param context: Who requested discovery.
        :returns: Implementation metadata.
        """
        from prophetovol.registry.catalog import get_registry
        return get_registry(kind).describe(name)

    def data_versions(self, underlying: str, import_id: str | None = None,
                       states: list[VersionState] | None = None) -> list[DataVersionRecord]:
        """List data versions for review and coverage bounds.

        :param underlying: Underlying to inspect.
        :param import_id: Restrict to one import when supplied.
        :param states: Restrict to these version states when supplied.
        :returns: Version records in as-of/import order.
        """
        return self.storage.list_versions(underlying, import_id, states)

    def import_snapshot(self, import_id: str, day: date, columns: list[str] | None = None) -> pa.Table:
        """Read an import's normalized snapshot for quality review.

        :param import_id: Import being reviewed.
        :param day: Snapshot date.
        :param columns: Columns to return, or all columns.
        :returns: Arrow table of the snapshot's rows.
        """
        return self.storage.read_import_snapshot(import_id, day, columns)

    @audited("docs.generate")
    def generate_docs(self, output: str | os.PathLike[str], context: CallContext, check: bool = False) -> list[str]:
        """Generate deterministic reStructuredText reference documentation from live schemas.

        :param output: Directory for generated reference files.
        :param context: Who requested generation.
        :param check: Compare existing files without writing; refuse stale or missing files.
        :returns: Generated or checked file paths.
        """
        from prophetovol.documentation import reference_documents
        documents = reference_documents()
        folder = Path(output)
        if check:
            stale = [name for name, text in documents.items()
                     if not (folder / name).is_file() or (folder / name).read_text(encoding="utf-8") != text]
            if stale:
                raise ValidationFailed([ValidationIssue("docs", "stale or missing: " + ", ".join(stale))])
        else:
            folder.mkdir(parents=True, exist_ok=True)
            for name, text in documents.items():
                (folder / name).write_text(text, encoding="utf-8", newline="\n")
        return [str(folder / name) for name in documents]
