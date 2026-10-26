"""Records kept in the catalog (requirements §5.2): imports, data versions, definitions, jobs and attempts.

Every instant is an aware UTC datetime.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from prophetovol.core.context import Channel


class ImportStatus(StrEnum):
    """The life of an import (DATA-11, DATA-31)."""

    INGESTING = "ingesting"
    STAGED = "staged"
    COMMITTED = "committed"
    DISCARDED = "discarded"
    FAILED = "failed"


class VersionState(StrEnum):
    """The state of one data version (DATA-40, DATA-50, DATA-51)."""

    STAGED = "staged"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DELETED = "deleted"
    DISCARDED = "discarded"
    PURGED = "purged"


class JobStatus(StrEnum):
    """The life of a background job (INT-21)."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AttemptOutcome(StrEnum):
    """How a requested operation ended (AUD-2)."""

    OK = "ok"
    REJECTED = "rejected"
    ERROR = "error"


class ImportFile(BaseModel):
    """One file of an import (DATA-4, DATA-12)."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(description="The file name as uploaded, or the path inside a zip archive.")
    size_bytes: int = Field(ge=0, description="The file's uncompressed size in bytes.")
    sha256: str = Field(description="The SHA-256 of the file's contents, as 64 hexadecimal characters.")


class DataImport(BaseModel):
    """One import of vendor files (requirements §5.2, DATA-11)."""

    import_id: str = Field(description="The import's id.")
    underlying: str = Field(description="The underlying the import's files contain (one per import, DATA-3).")
    data_source: str = Field(description="The data source the files are in, for example ivolatility_eod.")
    status: ImportStatus = Field(description="Where the import is in its life: ingesting, staged, committed, "
                                             "discarded or failed.")
    files: list[ImportFile] = Field(description="The import's files with their sizes and hashes.")
    rows: int | None = Field(default=None, description="Rows read from the files, once known.")
    first_as_of_date: date | None = Field(default=None, description="First snapshot date in the import.")
    last_as_of_date: date | None = Field(default=None, description="Last snapshot date in the import.")
    quality_report: dict[str, Any] | None = Field(default=None, description="The quality report (DATA-20), once validated.")
    commit_choice: str | None = Field(default=None, description="The commit choice (replace, add_new or cancel), once made.")
    error: str | None = Field(default=None, description="Why the import failed, if it did.")
    actor: str = Field(description="Who started the import (AUD-1).")
    channel: Channel = Field(description="The client the import came through (AUD-1).")
    created_at: datetime = Field(description="When the import started (UTC).")
    committed_at: datetime | None = Field(default=None, description="When the import was committed or cancelled (UTC).")


class DataVersionRecord(BaseModel):
    """The market snapshot one import supplied for one underlying and as-of time (DATA-40, DATA-41)."""

    underlying: str = Field(description="The underlying.")
    as_of: datetime = Field(description="The snapshot's as-of instant (UTC).")
    as_of_date: date = Field(description="The snapshot's date.")
    import_id: str = Field(description="The import that supplied the snapshot.")
    state: VersionState = Field(description="staged, active, superseded, deleted, discarded or purged. At most one "
                                            "version per underlying and as-of time is active.")
    contracts: int = Field(ge=0, description="Number of option contracts in the snapshot.")
    quality_flags: list[str] = Field(default_factory=list, description="Quality checks that flagged this snapshot.")
    state_changed_at: datetime = Field(description="When the version entered its current state (UTC).")


class DefinitionVersion(BaseModel):
    """One published version of a versioned definition: an underlying, a data source, later specs (VER-1)."""

    kind: str = Field(description="What the definition is: underlying or data_source (more kinds in later phases).")
    key: str = Field(description="The definition's id within its kind, for example SPX.")
    version: int = Field(ge=1, description="The version number, from 1, increasing by one per published change.")
    body: dict[str, Any] = Field(description="The definition's content as JSON-compatible data.")
    content_hash: str = Field(description="SHA-256 of the body's canonical JSON (VER-2).")
    actor: str = Field(description="Who published this version (AUD-1).")
    channel: Channel = Field(description="The client it was published through (AUD-1).")
    created_at: datetime = Field(description="When it was published (UTC).")


class JobRecord(BaseModel):
    """A background operation with its status and progress (INT-21, INT-22)."""

    job_id: str = Field(description="The job's id.")
    kind: str = Field(description="What the job does, for example ingest, commit, purge or run.")
    params: dict[str, Any] = Field(default_factory=dict, description="The job's parameters as JSON-compatible data.")
    status: JobStatus = Field(description="queued, running, succeeded, failed or cancelled.")
    progress_done: int | None = Field(default=None, description="Units of work done, when known.")
    progress_total: int | None = Field(default=None, description="Units of work in total, when known.")
    progress_label: str = Field(default="", description="What the job is doing now, for people.")
    result: dict[str, Any] | None = Field(default=None, description="Links to what the job produced, such as an import or run id.")
    error: str | None = Field(default=None, description="Why the job failed, if it did.")
    cancel_requested: bool = Field(default=False, description="Whether cancellation was asked for (INT-24).")
    actor: str = Field(description="Who started the job (AUD-1).")
    channel: Channel = Field(description="The client the job was started through (AUD-1).")
    created_at: datetime = Field(description="When the job was submitted (UTC).")
    started_at: datetime | None = Field(default=None, description="When the job started running (UTC).")
    finished_at: datetime | None = Field(default=None, description="When the job finished (UTC).")


class AttemptRecord(BaseModel):
    """One requested operation and its outcome, including rejections (AUD-2). Never deleted."""

    attempt_id: str = Field(description="The attempt's id.")
    operation: str = Field(description="The service operation requested, for example data.commit.")
    params_summary: dict[str, Any] = Field(default_factory=dict, description="A summary of the request's parameters.")
    outcome: AttemptOutcome = Field(description="ok, rejected (with reasons) or error.")
    reasons: list[str] = Field(default_factory=list, description="Why the operation was rejected or failed.")
    actor: str = Field(description="Who asked (AUD-1).")
    channel: Channel = Field(description="The client the request came through (AUD-1).")
    attempted_at: datetime = Field(description="When the request was made (UTC).")
