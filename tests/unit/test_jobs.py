"""Persisted jobs and the job runner (INT-20 to INT-24, RUN-20)."""

from __future__ import annotations

import threading
import time

import pytest

from prophetovol.core.context import CallContext, Channel
from prophetovol.core.errors import ImmutableEntityError
from prophetovol.core.records import JobStatus
from prophetovol.runs.jobs import (INTERRUPTED_MESSAGE, STOPPED_MESSAGE, JobRunner, execute_job, new_job,
                                   recover_interrupted_jobs)
from prophetovol.storage.duckdb.adapter import DuckDBAdapter

CTX = CallContext(actor="alice", channel=Channel.GUI)
WAIT = 10


@pytest.fixture
def storage(tmp_path):
    a = DuckDBAdapter.open(tmp_path / "home")
    yield a
    a.close()


def make_runner(storage, **handlers):
    runner = JobRunner(storage, handlers)
    runner.start()
    return runner


def test_success_records_result_progress_and_times(storage):
    def handler(ctx):
        for i in range(1, 4):
            ctx.progress(i, 3, f"step {i}")
        return {"import_id": "imp_x", "params_seen": ctx.params["n"]}

    runner = make_runner(storage, demo=handler)
    job = runner.submit("demo", {"n": 3}, CTX)
    assert job.status is JobStatus.QUEUED  # submit returns at once; the worker runs it afterwards
    assert runner.wait(job.job_id, WAIT)
    done = storage.get_job(job.job_id)
    assert done.status is JobStatus.SUCCEEDED and done.result == {"import_id": "imp_x", "params_seen": 3}
    assert (done.progress_done, done.progress_total, done.progress_label) == (3, 3, "step 3")
    assert done.started_at <= done.finished_at and (done.actor, done.channel) == ("alice", Channel.GUI)
    runner.stop()


def test_jobs_run_one_at_a_time_in_submission_order(storage):
    order, active, peak = [], [0], [0]
    lock = threading.Lock()

    def handler(ctx):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        order.append(ctx.params["i"])
        time.sleep(0.02)
        with lock:
            active[0] -= 1

    runner = make_runner(storage, demo=handler)
    jobs = [runner.submit("demo", {"i": i}, CTX) for i in range(5)]
    for j in jobs:
        assert runner.wait(j.job_id, WAIT)
    assert order == [0, 1, 2, 3, 4] and peak[0] == 1
    runner.stop()


def test_a_failing_job_is_recorded_and_the_next_one_still_runs(storage):
    def bad(ctx):
        raise ValueError("boom")

    runner = make_runner(storage, bad=bad, good=lambda ctx: {"ok": True})
    first, second = runner.submit("bad", {}, CTX), runner.submit("good", {}, CTX)
    assert runner.wait(second.job_id, WAIT)
    failed = storage.get_job(first.job_id)
    assert failed.status is JobStatus.FAILED and failed.error == "boom" and failed.finished_at
    assert storage.get_job(second.job_id).status is JobStatus.SUCCEEDED
    runner.stop()


def test_cancelling_a_queued_job_takes_effect_at_once(storage):
    release, calls = threading.Event(), []

    def blocking(ctx):
        release.wait(WAIT)

    runner = make_runner(storage, block=blocking, other=lambda ctx: calls.append(1))
    first, second = runner.submit("block", {}, CTX), runner.submit("other", {}, CTX)
    cancelled = runner.cancel(second.job_id)
    assert cancelled.status is JobStatus.CANCELLED and cancelled.cancel_requested
    assert storage.get_job(second.job_id).status is JobStatus.CANCELLED
    release.set()
    assert runner.wait(first.job_id, WAIT) and runner.wait(second.job_id, WAIT)
    runner.stop()
    assert calls == []  # the cancelled job never ran


def test_cancelling_a_running_job_stops_it_at_a_safe_point(storage):
    started = threading.Event()

    def looping(ctx):
        started.set()
        for i in range(1000):
            ctx.check_cancelled()
            ctx.progress(i, 1000)
            time.sleep(0.005)
        return {"finished": True}

    runner = make_runner(storage, loop=looping)
    job = runner.submit("loop", {}, CTX)
    assert started.wait(WAIT)
    runner.cancel(job.job_id)
    assert runner.wait(job.job_id, WAIT)
    final = storage.get_job(job.job_id)
    assert final.status is JobStatus.CANCELLED and final.cancel_requested and final.result is None
    assert final.progress_done < 999
    runner.stop()


def test_finished_jobs_cannot_be_cancelled_and_unknown_kinds_are_refused(storage):
    runner = make_runner(storage, demo=lambda ctx: None)
    job = runner.submit("demo", {}, CTX)
    runner.wait(job.job_id, WAIT)
    with pytest.raises(ImmutableEntityError, match="already finished"):
        runner.cancel(job.job_id)
    with pytest.raises(ValueError, match="no handler for job kind 'nope'"):
        runner.submit("nope", {}, CTX)
    runner.stop()


def test_stop_finishes_the_running_job_and_cancels_queued_ones(storage):
    started, release = threading.Event(), threading.Event()

    def blocking(ctx):
        started.set()
        release.wait(WAIT)
        return {"done": True}

    runner = make_runner(storage, block=blocking)
    first, second = runner.submit("block", {}, CTX), runner.submit("block", {}, CTX)
    assert started.wait(WAIT)
    threading.Timer(0.2, release.set).start()
    runner.stop()
    assert storage.get_job(first.job_id).status is JobStatus.SUCCEEDED
    queued = storage.get_job(second.job_id)
    assert queued.status is JobStatus.CANCELLED and queued.error == STOPPED_MESSAGE


def test_progress_is_throttled_but_always_written_at_completion(storage):
    times = iter([0.0, 0.1, 0.2, 0.6, 0.7])
    writes = []
    original = storage.update_job
    storage.update_job = lambda rec: (writes.append(rec.progress_done), original(rec))  # type: ignore[method-assign]

    def handler(ctx):
        for done in range(1, 6):
            ctx.progress(done, 5)

    record = new_job("demo", {}, CTX)
    storage.insert_job(record)
    execute_job(record, handler, storage, clock=lambda: next(times))
    # running (no progress yet), progress at t=0.0 and t=0.6 only, then the final save with the last value
    assert writes == [None, 1, 4, 5]
    assert storage.get_job(record.job_id).progress_done == 5


def test_keyboard_interrupt_marks_the_job_cancelled_and_propagates(storage):
    def interrupted(ctx):
        raise KeyboardInterrupt

    record = new_job("demo", {}, CTX)
    storage.insert_job(record)
    with pytest.raises(KeyboardInterrupt):
        execute_job(record, interrupted, storage)
    got = storage.get_job(record.job_id)
    assert got.status is JobStatus.CANCELLED and got.error == "cancelled by the user"


def test_interrupted_jobs_are_recovered_as_failed(storage):
    ids = {}
    for status in (JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.SUCCEEDED):
        rec = new_job("demo", {}, CTX)
        rec.status = status
        storage.insert_job(rec)
        ids[status] = rec.job_id
    changed = recover_interrupted_jobs(storage)
    assert sorted(changed) == sorted([ids[JobStatus.QUEUED], ids[JobStatus.RUNNING]])
    for status in (JobStatus.QUEUED, JobStatus.RUNNING):
        job = storage.get_job(ids[status])
        assert job.status is JobStatus.FAILED and job.error == INTERRUPTED_MESSAGE and job.finished_at
    assert storage.get_job(ids[JobStatus.SUCCEEDED]).status is JobStatus.SUCCEEDED
    assert recover_interrupted_jobs(storage) == []
