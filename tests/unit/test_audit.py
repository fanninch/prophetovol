"""The attempts log (AUD-1, AUD-2) and the service's audited and job operations."""

from __future__ import annotations

import pytest

from prophetovol.core.context import CallContext, Channel
from prophetovol.core.errors import ConfigurationError, ImmutableEntityError, ValidationFailed
from prophetovol.core.records import AttemptOutcome, JobStatus
from prophetovol.runs.audit import audited, summarize_params
from prophetovol.runs.jobs import new_job
from prophetovol.runs.service import UNDERLYING, BacktestService

BOB = CallContext(actor="bob", channel=Channel.API)


@pytest.fixture
def svc(tmp_path):
    with BacktestService.open(tmp_path / "home") as s:
        yield s


def spx_body(svc):
    return svc.storage.get_definition(UNDERLYING, "SPX").body


class TestPublishing:
    def test_publish_records_an_ok_attempt_with_actor_and_channel(self, svc):
        body = spx_body(svc) | {"description": "edited"}
        version, created = svc.publish_underlying(body, BOB)
        assert created and version.version == 2 and version.actor == "bob"
        attempt = svc.page_attempts(operation="reference.publish_underlying").items[0]
        assert attempt.outcome is AttemptOutcome.OK and (attempt.actor, attempt.channel) == ("bob", Channel.API)
        assert attempt.params_summary == {"body": f"<dict of {len(body)}>"}

    def test_unchanged_content_publishes_nothing(self, svc):
        _, created = svc.publish_underlying(spx_body(svc), BOB)
        assert not created and len(svc.storage.list_definition_versions(UNDERLYING, "SPX")) == 1

    def test_invalid_configuration_is_rejected_with_located_reasons(self, svc):
        body = spx_body(svc) | {"multiplier": -5}
        with pytest.raises(ValidationFailed) as info:
            svc.publish_underlying(body, BOB)
        assert info.value.issues[0].path == "multiplier"
        attempt = svc.page_attempts().items[0]
        assert attempt.outcome is AttemptOutcome.REJECTED and attempt.reasons[0].startswith("multiplier: ")
        assert len(svc.storage.list_definition_versions(UNDERLYING, "SPX")) == 1

    def test_data_source_publishing(self, svc):
        body = svc.storage.get_definition("data_source", "ivolatility_eod").body | {"parity_strikes": 4}
        version, created = svc.publish_data_source(body, BOB)
        assert created and svc.data_source("ivolatility_eod").parity_strikes == 4
        with pytest.raises(ValidationFailed):
            svc.publish_data_source(body | {"parity_strikes": 1}, BOB)

    def test_unexpected_errors_are_recorded_as_errors_and_propagate(self, svc, monkeypatch):
        def broken(*args, **kwargs):
            raise RuntimeError("disk full")

        monkeypatch.setattr(svc.storage, "save_definition", broken)
        with pytest.raises(RuntimeError, match="disk full"):
            svc.publish_underlying(spx_body(svc) | {"description": "x"}, BOB)
        attempt = svc.page_attempts().items[0]
        assert attempt.outcome is AttemptOutcome.ERROR and attempt.reasons == ["disk full"]

    def test_a_failing_attempt_write_never_hides_the_result(self, svc, monkeypatch):
        def broken(record):
            raise RuntimeError("cannot write")

        monkeypatch.setattr(svc.storage, "append_attempt", broken)
        version, created = svc.publish_underlying(spx_body(svc) | {"description": "y"}, BOB)
        assert created


class TestDecorator:
    def test_methods_without_context_cannot_be_audited(self):
        with pytest.raises(TypeError, match="must take a 'context' argument"):
            @audited("x.y")
            def f(self, a):
                """Doc.

                :param a: A.
                """

    def test_summary_keeps_simple_values_only(self):
        summary = summarize_params({"self": object(), "context": BOB, "name": "x" * 300, "n": 3, "flag": True,
                                    "none": None, "items": [1, 2, 3], "obj": object()})
        assert set(summary) == {"name", "n", "flag", "none", "items", "obj"}
        assert len(summary["name"]) == 201 and summary["name"].endswith("…")
        assert summary["items"] == "<list of 3>" and summary["obj"] == "<object>"


class TestServiceJobs:
    def test_background_jobs_and_audited_cancel(self, svc):
        svc.start_jobs({"demo": lambda ctx: {"ok": True}})
        job = svc.submit_job("demo", {"x": 1}, BOB)
        assert svc.jobs.wait(job.job_id, 10)
        assert svc.get_job(job.job_id).status is JobStatus.SUCCEEDED
        assert svc.page_jobs(statuses=[JobStatus.SUCCEEDED]).total == 1
        with pytest.raises(ImmutableEntityError):
            svc.cancel_job(job.job_id, BOB)
        cancel_attempt = svc.page_attempts(operation="jobs.cancel").items[0]
        assert cancel_attempt.outcome is AttemptOutcome.REJECTED and "already finished" in cancel_attempt.reasons[0]

    def test_foreground_job_is_recorded(self, svc):
        job = svc.run_job("demo", {"x": 2}, lambda ctx: {"rows": 10}, BOB)
        assert job.status is JobStatus.SUCCEEDED and svc.get_job(job.job_id).result == {"rows": 10}

    def test_runner_rules(self, svc):
        with pytest.raises(ConfigurationError, match="not running"):
            svc.jobs
        reader = svc.reader()
        with pytest.raises(ConfigurationError, match="only the owning service"):
            reader.start_jobs({})
        reader.close()
        svc.start_jobs({})
        with pytest.raises(ConfigurationError, match="already running"):
            svc.start_jobs({})
        svc.stop_jobs()
        svc.stop_jobs()  # stopping twice is harmless


def test_reopening_recovers_jobs_a_crashed_process_left_running(tmp_path):
    home = tmp_path / "home"
    with BacktestService.open(home) as svc:
        rec = new_job("ingest", {}, BOB)
        rec.status = JobStatus.RUNNING
        svc.storage.insert_job(rec)  # as if the process died mid-job
    with BacktestService.open(home) as svc:
        assert svc.recovered_jobs == [rec.job_id]
        assert svc.get_job(rec.job_id).status is JobStatus.FAILED
