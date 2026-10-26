"""``BacktestService``: the single owner of all storage access (ARC-1).

The CLI, the API and later an agent call only this service. One process opens a home directory
at a time (INT-41); inside it, one owning service holds the databases and request threads use
:meth:`BacktestService.reader` (ARC-4).
"""

from __future__ import annotations

import os
from pathlib import Path
from types import TracebackType
from typing import Any

import pydantic

from prophetovol.core.context import CallContext, Channel
from prophetovol.core.errors import ConfigurationError, ValidationFailed
from prophetovol.core.home import resolve_home
from prophetovol.core.paging import Page
from prophetovol.core.records import AttemptRecord, DefinitionVersion, JobRecord, JobStatus
from prophetovol.reference.calendar import TradingCalendar, nyse_calendar
from prophetovol.reference.defaults import default_data_sources, default_underlyings
from prophetovol.reference.models import DataSource, Underlying
from prophetovol.runs.audit import audited
from prophetovol.runs.jobs import JobHandler, JobRunner, execute_job, new_job, recover_interrupted_jobs
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
