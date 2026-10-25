"""Shared fixtures: temporary home directories and a clean environment."""

from __future__ import annotations

from pathlib import Path

import pytest

from prophetovol.core.home import HOME_ENV_VAR


@pytest.fixture(autouse=True)
def _no_home_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a developer's own ``PROPHETOVOL_HOME`` from leaking into tests.

    :param monkeypatch: pytest's monkeypatch fixture.
    """
    monkeypatch.delenv(HOME_ENV_VAR, raising=False)


@pytest.fixture
def tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fresh home directory, also set as ``PROPHETOVOL_HOME``.

    :param tmp_path: pytest's per-test temporary directory.
    :param monkeypatch: pytest's monkeypatch fixture.
    :returns: The home directory path (not yet created).
    """
    home = tmp_path / "home"
    monkeypatch.setenv(HOME_ENV_VAR, str(home))
    return home
