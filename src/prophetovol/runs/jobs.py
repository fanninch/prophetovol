"""Persisted background jobs (INT-20 to INT-24, RUN-20) and the runner that executes them.

A job is recorded in the catalog when it is submitted, so its history survives a restart
(INT-22). The :class:`JobRunner` executes write jobs one at a time in submission order on a single
worker thread (INT-23), while request threads keep reading through their own cursors (ARC-4).
The CLI runs a job in its own thread instead, through :func:`execute_job`, and records it the
same way (plan §4.8).

A handler does the job's work. It receives a :class:`JobContext`, reports progress through it,
and calls :meth:`JobContext.check_cancelled` at safe points (between partitions for ingest,
between steps for runs, INT-24).
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

from prophetovol.core.context import CallContext
from prophetovol.core.errors import ImmutableEntityError
from prophetovol.core.ids import new_id, utc_now
from prophetovol.core.records import JobRecord, JobStatus
from prophetovol.storage.adapter import StorageAdapter

log = logging.getLogger(__name__)

INTERRUPTED_MESSAGE = "interrupted: the process running this job ended before it finished"
"""The error recorded on jobs found queued or running when a home directory is opened (RUN-20)."""

STOPPED_MESSAGE = "cancelled: the job runner was stopped before this job started"
"""The error recorded on queued jobs when the runner is stopped cleanly."""

PROGRESS_INTERVAL_SECONDS = 0.5
"""Progress is written to the catalog at most this often, and always at completion (plan §4.8)."""

FINISHED = (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED)
"""The statuses a job never leaves."""


class JobCancelled(Exception):
    """Raised by :meth:`JobContext.check_cancelled` to stop a job at a safe point."""


class JobContext:
    """What a job handler gets: its parameters, storage, progress reporting and cancellation.

    :param record: The job's record; the context updates it.
    :param storage: Storage for the job's thread.
    :param cancel_event: Set when cancellation is requested.
    :param clock: Monotonic clock in seconds, for progress throttling.
    """

    def __init__(self, record: JobRecord, storage: StorageAdapter, cancel_event: threading.Event,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.record = record
        self.storage = storage
        self._cancel = cancel_event
        self._clock = clock
        self._last_write: float | None = None

    @property
    def params(self) -> dict[str, Any]:
        """The job's parameters."""
        return self.record.params

    @property
    def context(self) -> CallContext:
        """Who started the job, through which channel."""
        return CallContext(actor=self.record.actor, channel=self.record.channel)

    @property
    def cancelled(self) -> bool:
        """Whether cancellation has been requested."""
        return self._cancel.is_set()

    def check_cancelled(self) -> None:
        """Stop the job here if cancellation has been requested.

        :raises JobCancelled: If it has.
        """
        if self._cancel.is_set():
            raise JobCancelled()

    def progress(self, done: int, total: int | None = None, label: str = "") -> None:
        """Report progress; it is written at most every half second, and always at completion.

        :param done: Units of work done.
        :param total: Units of work in total, when known.
        :param label: What the job is doing now, for people.
        """
        self.record.progress_done = done
        self.record.progress_total = total
        self.record.progress_label = label
        now = self._clock()
        if self._last_write is None or now - self._last_write >= PROGRESS_INTERVAL_SECONDS:
            self._last_write = now
            self.save()

    def save(self) -> None:
        """Write the job's record, including whether cancellation was requested."""
        self.record.cancel_requested = self.record.cancel_requested or self._cancel.is_set()
        self.storage.update_job(self.record)


JobHandler = Callable[[JobContext], dict[str, Any] | None]
"""A job's work: it returns links to what it produced (such as an import id), or ``None``."""


def new_job(kind: str, params: dict[str, Any], context: CallContext) -> JobRecord:
    """A new job record in status ``queued``.

    :param kind: What the job does.
    :param params: Its parameters as JSON-compatible data.
    :param context: Who is submitting it, through which channel.
    :returns: The record (not yet stored).
    """
    return JobRecord(job_id=new_id("job"), kind=kind, params=params, status=JobStatus.QUEUED,
                     actor=context.actor, channel=context.channel, created_at=utc_now())


def execute_job(record: JobRecord, handler: JobHandler, storage: StorageAdapter,
                cancel_event: threading.Event | None = None,
                clock: Callable[[], float] = time.monotonic) -> JobRecord:
    """Run a stored job to completion in the calling thread, recording every state change.

    The handler's result marks the job ``succeeded``; :class:`JobCancelled` marks it ``cancelled``;
    any other exception marks it ``failed`` with the exception's message (and is not re-raised,
    except ``KeyboardInterrupt``, which marks it cancelled first). The last reported progress is
    always written with the final status.

    :param record: The job, already stored, in status ``queued``.
    :param handler: The job's work.
    :param storage: Storage for this thread.
    :param cancel_event: Set to request cancellation; a new, unset event when omitted.
    :param clock: Monotonic clock for progress throttling.
    :returns: The finished record.
    """
    ctx = JobContext(record, storage, cancel_event or threading.Event(), clock)
    record.status, record.started_at = JobStatus.RUNNING, utc_now()
    ctx.save()
    try:
        record.result = handler(ctx)
        record.status = JobStatus.SUCCEEDED
    except JobCancelled:
        record.status = JobStatus.CANCELLED
    except KeyboardInterrupt:
        record.status, record.error, record.finished_at = JobStatus.CANCELLED, "cancelled by the user", utc_now()
        ctx.save()
        raise
    except Exception as exc:  # noqa: BLE001 - a job's failure is recorded, not propagated
        log.exception("job %s (%s) failed", record.job_id, record.kind)
        record.status, record.error = JobStatus.FAILED, str(exc) or type(exc).__name__
    record.finished_at = utc_now()
    ctx.save()
    return record


def recover_interrupted_jobs(storage: StorageAdapter) -> list[str]:
    """Mark jobs left queued or running by a previous process as failed, "interrupted" (RUN-20).

    Call this only from the process that owns the home directory, when it opens it.

    :param storage: The owner's storage.
    :returns: The ids of the jobs changed.
    """
    changed = []
    while True:
        page = storage.page_jobs(limit=500, statuses=[JobStatus.QUEUED, JobStatus.RUNNING])
        if not page.items:
            return changed
        for job in page.items:
            job.status, job.error, job.finished_at = JobStatus.FAILED, INTERRUPTED_MESSAGE, utc_now()
            storage.update_job(job)
            changed.append(job.job_id)


class JobRunner:
    """Executes submitted jobs one at a time, in submission order, on one worker thread (INT-23).

    :param storage: The owning storage; the runner makes its own cursors from it for each thread.
    :param handlers: The handler for each job kind.
    :param clock: Monotonic clock for progress throttling.
    """

    def __init__(self, storage: StorageAdapter, handlers: dict[str, JobHandler],
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._storage = storage
        self._handlers = dict(handlers)
        self._clock = clock
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._lock = threading.Lock()
        self._state: dict[str, JobStatus] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._done: dict[str, threading.Event] = {}
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the worker thread (once)."""
        if self._thread is None:
            self._thread = threading.Thread(target=self._work, name="prophetovol-jobs", daemon=True)
            self._thread.start()

    def stop(self, timeout: float | None = None) -> None:
        """Stop after the running job finishes; jobs still queued are marked cancelled.

        :param timeout: Seconds to wait for the running job; wait as long as it takes when omitted.
        """
        with self._lock:
            queued = [j for j, s in self._state.items() if s is JobStatus.QUEUED]
            for job_id in queued:
                self._state[job_id] = JobStatus.CANCELLED
        if queued:
            storage = self._storage.reader()
            try:
                for job_id in queued:
                    job = storage.get_job(job_id)
                    job.status, job.error, job.finished_at = JobStatus.CANCELLED, STOPPED_MESSAGE, utc_now()
                    storage.update_job(job)
                    self._done[job_id].set()
            finally:
                storage.close()
        self._queue.put(None)
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def submit(self, kind: str, params: dict[str, Any], context: CallContext) -> JobRecord:
        """Record a job and queue it.

        :param kind: What the job does; a kind with a handler.
        :param params: Its parameters as JSON-compatible data.
        :param context: Who is submitting it.
        :returns: The stored record, in status ``queued``.
        :raises ValueError: If no handler exists for the kind.
        """
        if kind not in self._handlers:
            raise ValueError(f"no handler for job kind {kind!r}")
        record = new_job(kind, params, context)
        storage = self._storage.reader()
        try:
            storage.insert_job(record)
        finally:
            storage.close()
        with self._lock:
            self._state[record.job_id] = JobStatus.QUEUED
            self._cancel[record.job_id] = threading.Event()
            self._done[record.job_id] = threading.Event()
        self._queue.put(record.job_id)
        return record

    def cancel(self, job_id: str) -> JobRecord:
        """Cancel a job: at once if it is queued, at its next safe point if it is running (INT-24).

        :param job_id: The job.
        :returns: The job's record after the request.
        :raises NotFoundError: If the job does not exist.
        :raises ImmutableEntityError: If the job has already finished.
        """
        storage = self._storage.reader()
        try:
            job = storage.get_job(job_id)
            with self._lock:
                state = self._state.get(job_id, job.status)
                if state in FINISHED:
                    raise ImmutableEntityError(f"job {job_id} has already finished ({state})")
                if state is JobStatus.QUEUED:
                    self._state[job_id] = JobStatus.CANCELLED
                    job.status, job.finished_at = JobStatus.CANCELLED, utc_now()
                else:
                    self._cancel[job_id].set()
                job.cancel_requested = True
                storage.update_job(job)
            if job.status is JobStatus.CANCELLED:
                self._done[job_id].set()
            return job
        finally:
            storage.close()

    def wait(self, job_id: str, timeout: float | None = None) -> bool:
        """Wait until a job submitted to this runner has finished.

        :param job_id: The job.
        :param timeout: Seconds to wait at most; as long as it takes when omitted.
        :returns: Whether the job finished within the timeout.
        """
        return self._done[job_id].wait(timeout)

    def _work(self) -> None:
        """The worker loop: take the next job, skip it if cancelled, otherwise execute it."""
        storage = self._storage.reader()
        try:
            while True:
                job_id = self._queue.get()
                if job_id is None:
                    return
                with self._lock:
                    if self._state.get(job_id) is not JobStatus.QUEUED:
                        continue
                    self._state[job_id] = JobStatus.RUNNING
                try:
                    record = storage.get_job(job_id)
                    final = execute_job(record, self._handlers[record.kind], storage, self._cancel[job_id], self._clock)
                    with self._lock:
                        self._state[job_id] = final.status
                except Exception:  # noqa: BLE001 - storage trouble must not kill the worker
                    log.exception("could not record the outcome of job %s", job_id)
                    with self._lock:
                        self._state[job_id] = JobStatus.FAILED
                finally:
                    self._done[job_id].set()
        finally:
            storage.close()
