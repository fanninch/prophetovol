"""The adapter contract suite runs against every storage adapter (DATA-84, TEST-7).

Phase 1 has one adapter. Another adapter joins by adding its factory to ``ADAPTERS``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from prophetovol.storage.adapter import StorageAdapter
from prophetovol.storage.duckdb.adapter import DuckDBAdapter

ADAPTERS: dict[str, Callable[[Path], StorageAdapter]] = {
    "duckdb": DuckDBAdapter.open,
}


@pytest.fixture(params=sorted(ADAPTERS))
def open_adapter(request: pytest.FixtureRequest) -> Callable[[Path], StorageAdapter]:
    """The factory of the adapter under test.

    :param request: pytest's request, carrying the adapter name.
    :returns: A function opening an adapter on a home directory.
    """
    return ADAPTERS[request.param]


@pytest.fixture
def adapter(open_adapter: Callable[[Path], StorageAdapter], tmp_path: Path) -> Iterator[StorageAdapter]:
    """An adapter on a fresh home directory, closed afterwards.

    :param open_adapter: The adapter factory.
    :param tmp_path: pytest's per-test temporary directory.
    :returns: The adapter.
    """
    a = open_adapter(tmp_path / "home")
    yield a
    a.close()
