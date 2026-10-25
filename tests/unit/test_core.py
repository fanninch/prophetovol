"""Home resolution, call context, software versions, errors and logging."""

import getpass
import logging
import platform
from importlib import metadata
from pathlib import Path

import pydantic
import pytest

from prophetovol.core.context import CallContext, Channel, current_actor
from prophetovol.core.errors import (HomeLockedError, NotFoundError, PointInTimeError, ProphetoVolError,
                                     ValidationFailed, ValidationIssue)
from prophetovol.core.home import DEFAULT_HOME_DIRNAME, HOME_ENV_VAR, resolve_home
from prophetovol.core.log import configure_logging
from prophetovol.core.versions import software_versions


class TestResolveHome:
    def test_explicit_path_wins_over_environment(self, tmp_path):
        env = {HOME_ENV_VAR: str(tmp_path / "from_env")}
        assert resolve_home(tmp_path / "explicit", environ=env) == (tmp_path / "explicit").resolve()

    def test_environment_used_when_no_explicit_path(self, tmp_path):
        env = {HOME_ENV_VAR: str(tmp_path / "from_env")}
        assert resolve_home(None, environ=env) == (tmp_path / "from_env").resolve()

    def test_default_is_dot_prophetovol_in_user_home(self):
        assert resolve_home(None, environ={}) == (Path.home() / DEFAULT_HOME_DIRNAME).resolve()

    def test_empty_values_fall_through(self, tmp_path):
        assert resolve_home("", environ={HOME_ENV_VAR: ""}) == (Path.home() / DEFAULT_HOME_DIRNAME).resolve()

    def test_relative_and_tilde_paths_become_absolute(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert resolve_home("rel", environ={}) == (tmp_path / "rel").resolve()
        assert resolve_home("~/x", environ={}) == (Path.home() / "x").resolve()

    def test_nothing_is_created(self, tmp_path):
        resolve_home(tmp_path / "not_created", environ={})
        assert not (tmp_path / "not_created").exists()

    def test_reads_os_environ_by_default(self, tmp_home):
        assert resolve_home() == tmp_home.resolve()


class TestCallContext:
    def test_actor_defaults_to_operating_system_user(self):
        assert CallContext(channel="cli").actor == getpass.getuser() == current_actor()

    def test_for_channel(self):
        ctx = CallContext.for_channel("gui")
        assert ctx.channel is Channel.GUI and ctx.actor == current_actor()

    def test_unknown_channel_rejected(self):
        with pytest.raises(pydantic.ValidationError):
            CallContext(channel="email")

    def test_frozen(self):
        ctx = CallContext(channel=Channel.API, actor="alice")
        with pytest.raises(pydantic.ValidationError):
            ctx.actor = "bob"

    def test_channels_are_the_four_of_aud_1(self):
        assert {c.value for c in Channel} == {"cli", "api", "gui", "library"}


def test_software_versions_cover_run_30():
    v = software_versions()
    assert v.prophetovol == "0.1.0"
    assert v.python == platform.python_version()
    assert v.duckdb == metadata.version("duckdb")
    assert v.ibis == metadata.version("ibis-framework")
    assert v.exchange_calendars == metadata.version("exchange_calendars")
    assert "not installed" not in v.model_dump().values()


class TestErrors:
    def test_hierarchy(self):
        for cls in (NotFoundError, PointInTimeError, HomeLockedError, ValidationFailed):
            assert issubclass(cls, ProphetoVolError)

    def test_validation_failed_lists_every_issue_with_its_path(self):
        err = ValidationFailed([ValidationIssue("legs.0.ratio", "must be positive"), ValidationIssue("", "empty spec")])
        assert len(err.issues) == 2
        assert "legs.0.ratio: must be positive" in str(err) and "  - empty spec" in str(err)


def test_configure_logging_to_file(tmp_path):
    log_file = tmp_path / "logs" / "server.log"
    configure_logging("INFO", log_file)
    configure_logging("INFO", log_file)  # a second call replaces the handlers instead of adding more
    logger = logging.getLogger("prophetovol.test")
    logger.info("hello")
    root = logging.getLogger("prophetovol")
    assert len(root.handlers) == 2
    for handler in root.handlers:
        handler.flush()
    assert "INFO prophetovol.test: hello" in log_file.read_text(encoding="utf-8")
    configure_logging()  # restore: stderr only, warnings and above
    assert len(root.handlers) == 1
