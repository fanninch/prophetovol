"""The storage adapter interface (DATA-82, DATA-83).

Everything above the adapter works in underlyings, as-of times, snapshots and versions; files,
partitions, tables and transactions are known only to the adapter. Phase 1 has one
implementation, DuckDB plus Parquet (``storage.duckdb``), and every implementation must pass the
contract suite in ``tests/contract`` (DATA-84).

The interface grows with the plan's phases: this version has the catalog, staged market data,
jobs, attempts, the Phase 7 data lifecycle and Phase 10's chunked market reads for runs. Run results
arrive with Phase 14.

An adapter object is used from one thread at a time. Request threads use :meth:`reader`, which
returns an adapter on independent cursors of the same databases (ARC-4).
"""

from __future__ import annotations

from collections.abc import Callable

from abc import ABC, abstractmethod
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa

from prophetovol.data.lifecycle import ChangePreview, CommitChoice, DataSelection, OverlapItem, RunImpact
from prophetovol.core.context import CallContext
from prophetovol.core.paging import Page
from prophetovol.core.records import (AttemptRecord, DataImport, DataVersionRecord, DefinitionVersion, JobRecord,
                                      JobStatus, VersionState)


class StorageAdapter(ABC):
    """Every storage operation the service needs."""

    # --- lifecycle -------------------------------------------------------------------------

    @property
    @abstractmethod
    def home(self) -> Path:
        """The home directory this adapter stores in."""

    @property
    @abstractmethod
    def schema_versions(self) -> dict[str, int]:
        """The schema version of each database, for example ``{"catalog": 1, "results": 1}``."""

    @abstractmethod
    def reader(self) -> StorageAdapter:
        """An adapter on independent cursors of the same databases, for another thread (ARC-4).

        Closing it never closes the owner's connections.

        :returns: The reader adapter.
        """

    @abstractmethod
    def close(self) -> None:
        """Release this adapter's connections (the owner's close releases the databases)."""

    # --- versioned definitions (VER-1, VER-2) ----------------------------------------------

    @abstractmethod
    def save_definition(self, kind: str, key: str, body: dict[str, Any], context: CallContext) -> tuple[DefinitionVersion, bool]:
        """Publish a new version of a definition unless its content is unchanged.

        :param kind: The definition kind, for example ``underlying``.
        :param key: The definition's id within its kind.
        :param body: The content as JSON-compatible data.
        :param context: Who is publishing, through which channel.
        :returns: The latest version, and whether this call created it (``False`` when the content
            equals the latest version's, in which case nothing is published).
        """

    @abstractmethod
    def get_definition(self, kind: str, key: str, version: int | None = None) -> DefinitionVersion:
        """Read one version of a definition.

        :param kind: The definition kind.
        :param key: The definition's id.
        :param version: The version; the latest when omitted.
        :returns: The definition version.
        :raises NotFoundError: If it does not exist.
        """

    @abstractmethod
    def list_definitions(self, kind: str) -> list[DefinitionVersion]:
        """The latest version of every definition of a kind, ordered by key.

        :param kind: The definition kind.
        :returns: The latest versions.
        """

    @abstractmethod
    def list_definition_versions(self, kind: str, key: str) -> list[DefinitionVersion]:
        """Every version of one definition, oldest first.

        :param kind: The definition kind.
        :param key: The definition's id.
        :returns: The versions.
        """

    # --- imports (DATA-11, DATA-12) ---------------------------------------------------------

    @abstractmethod
    def create_import(self, record: DataImport) -> None:
        """Record a new import.

        :param record: The import, usually in status ``ingesting``.
        """

    @abstractmethod
    def update_import(self, record: DataImport) -> None:
        """Replace an import's mutable fields (underlying, status, counts, dates, report, commit details, error).

        The underlying is known only once the files are parsed, so ingest sets it after creating the import.

        :param record: The import with its new values; identified by ``import_id``.
        :raises NotFoundError: If the import does not exist.
        """

    @abstractmethod
    def get_import(self, import_id: str) -> DataImport:
        """Read one import.

        :param import_id: The import's id.
        :returns: The import.
        :raises NotFoundError: If it does not exist.
        """

    @abstractmethod
    def page_imports(self, offset: int = 0, limit: int = 50, underlying: str | None = None) -> Page[DataImport]:
        """List imports, newest first.

        :param offset: Index of the first import to return.
        :param limit: Page size.
        :param underlying: Only imports of this underlying, when given.
        :returns: A page of imports.
        """

    @abstractmethod
    def find_imports_with_file_hash(self, sha256: str) -> list[str]:
        """Ids of imports, other than discarded ones, with a file of this hash (DATA-12).

        :param sha256: A file's SHA-256.
        :returns: The import ids, in creation order.
        """

    # --- staged market data (DATA-11, DATA-80) ---------------------------------------------

    @abstractmethod
    def write_market_partition(self, import_id: str, underlying: str, year: int, month: int, table: pa.Table) -> None:
        """Write one month of an import's normalized market snapshots.

        The rows must already be sorted by as-of time (then root, expiration, type and strike).
        Nothing becomes visible to runs until the import is committed.

        :param import_id: The import the rows belong to.
        :param underlying: Their underlying.
        :param year: The partition's year.
        :param month: The partition's month, 1 to 12.
        :param table: The rows.
        :raises ImmutableEntityError: If this import already has data for that month.
        """

    @abstractmethod
    def record_staged_versions(self, versions: list[DataVersionRecord]) -> None:
        """Record the data versions an import supplies, in state ``staged``, in one transaction.

        :param versions: One record per as-of time.
        """

    @abstractmethod
    def list_versions(self, underlying: str, import_id: str | None = None,
                      states: list[VersionState] | None = None) -> list[DataVersionRecord]:
        """Data versions of an underlying, ordered by as-of time, then import.

        :param underlying: The underlying.
        :param import_id: Only this import's versions, when given.
        :param states: Only versions in these states, when given.
        :returns: The versions.
        """

    @abstractmethod
    def read_import_snapshot(self, import_id: str, as_of_date: date, columns: list[str] | None = None) -> pa.Table:
        """Read one date's snapshot as an import supplied it, whatever its state (for review).

        :param import_id: The import.
        :param as_of_date: The snapshot date.
        :param columns: The columns to return; all when omitted.
        :returns: The rows, in stored order.
        """

    @abstractmethod
    def discard_import(self, import_id: str) -> None:
        """Delete a staged import's files and mark it and its versions discarded (DATA-31, cancel).

        :param import_id: The import.
        :raises ImmutableEntityError: If any of its versions was ever activated.
        """

    # --- jobs (INT-21, INT-22) ---------------------------------------------------------------

    @abstractmethod
    def insert_job(self, record: JobRecord) -> None:
        """Record a new job.

        :param record: The job.
        """

    @abstractmethod
    def update_job(self, record: JobRecord) -> None:
        """Replace a job's mutable fields (status, progress, result, error, cancellation, times).

        :param record: The job with its new values; identified by ``job_id``.
        :raises NotFoundError: If the job does not exist.
        """

    @abstractmethod
    def get_job(self, job_id: str) -> JobRecord:
        """Read one job.

        :param job_id: The job's id.
        :returns: The job.
        :raises NotFoundError: If it does not exist.
        """

    @abstractmethod
    def page_jobs(self, offset: int = 0, limit: int = 50, statuses: list[JobStatus] | None = None) -> Page[JobRecord]:
        """List jobs, newest first.

        :param offset: Index of the first job to return.
        :param limit: Page size.
        :param statuses: Only jobs in these statuses, when given.
        :returns: A page of jobs.
        """

    # --- attempts (AUD-2) --------------------------------------------------------------------

    @abstractmethod
    def append_attempt(self, record: AttemptRecord) -> None:
        """Record an attempt. Attempts are never changed or deleted.

        :param record: The attempt.
        """

    @abstractmethod
    def page_attempts(self, offset: int = 0, limit: int = 50, operation: str | None = None) -> Page[AttemptRecord]:
        """List attempts, newest first.

        :param offset: Index of the first attempt to return.
        :param limit: Page size.
        :param operation: Only attempts at this operation, when given.
        :returns: A page of attempts.
        """

    # --- data lifecycle (DATA-30 to DATA-70) -------------------------------------------------

    @abstractmethod
    def overlap(self, import_id: str) -> list[OverlapItem]:
        """Compare every staged snapshot with currently active data (DATA-30).

        :param import_id: A staged import.
        :returns: Incoming versions paired with their active overlaps, ordered by as-of.
        """

    @abstractmethod
    def run_data_impacts(self, run_id: str) -> list[RunImpact]:
        """Read the persisted superseded-data dates of a run (RUN-40).

        :param run_id: Run whose flags are requested.
        :returns: Affected dates grouped by underlying; empty if no invalidations exist.
        """

    @abstractmethod
    def commit_import(self, import_id: str, choice: CommitChoice) -> int:
        """Activate an import atomically, preserving old versions and invalidating dependent runs.

        :param import_id: Staged import to commit.
        :param choice: Replace overlaps, add new dates only, or cancel/discard.
        :returns: Number of snapshots activated.
        """

    @abstractmethod
    def preview_change(self, operation: str, selection: DataSelection) -> ChangePreview:
        """List eligible versions and dependent runs before delete or purge (DATA-52).

        :param operation: ``delete`` or ``purge``.
        :param selection: Import for purge, or inclusive underlying/date range.
        :returns: Review report with a token that detects intervening changes.
        """

    @abstractmethod
    def apply_change(self, preview: ChangePreview, progress: Callable[[int, int], None] | None = None) -> int:
        """Execute a confirmed preview, rejecting a changed scope before touching data.

        :param preview: The report the caller confirmed, including its original token.
        :param progress: Optional progress/cancellation callback between purge files; receives done and total.
        :returns: Number of versions deleted or purged.
        :raises ValidationFailed: If versions or dependent runs changed after review.
        """

    @abstractmethod
    def read_active_snapshot(self, underlying: str, as_of: datetime, columns: list[str] | None = None,
                             cutoff: datetime | None = None) -> pa.Table:
        """Read only the active version at the exact as-of instant, with an optional point-in-time guard.

        :param underlying: Underlying to read.
        :param as_of: Requested aware snapshot instant; no implicit carry-forward.
        :param columns: Columns to return; all when omitted.
        :param cutoff: Latest allowed aware instant; asking for later data raises PointInTimeError.
        :returns: Active rows or an empty table when no snapshot is active.
        """

    @abstractmethod
    def read_market_chunk(self, underlying: str, versions: list[DataVersionRecord], columns: list[str] | None = None,
                          max_days_to_expiry: float | None = None) -> pa.Table:
        """Read the rows of exactly these data versions, whatever their state now (plan §4.6, decision 30).

        A run reads its steps in chunks through this, with the versions captured at pre-flight.

        :param underlying: The underlying.
        :param versions: The versions to read, one per as-of time.
        :param columns: The columns to return; all when omitted.
        :param max_days_to_expiry: Only rows whose ``days_to_expiry`` is at most this (the spec's horizon,
            decision 31); every row when omitted.
        :returns: The rows, ordered by as-of time, then root, expiration, option type and strike where present.
        :raises NotFoundError: If a version's file no longer exists (it was purged).
        """

    @abstractmethod
    def read_index_levels(self, underlying: str, versions: list[DataVersionRecord]) -> dict[datetime, float]:
        """The index level of each of these data versions' snapshots.

        :param underlying: The underlying.
        :param versions: The versions, one per as-of time.
        :returns: The index level by as-of instant (aware, UTC).
        :raises NotFoundError: If a version's file no longer exists.
        """
