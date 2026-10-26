"""``BacktestService``: the single owner of all storage access (ARC-1).

The CLI, the API and later an agent call only this service. One process opens a home directory
at a time (INT-41); inside it, one owning service holds the databases and request threads use
:meth:`BacktestService.reader` (ARC-4).
"""

from __future__ import annotations

import os
from pathlib import Path
from types import TracebackType

from prophetovol.core.context import CallContext, Channel
from prophetovol.core.home import resolve_home
from prophetovol.reference.calendar import TradingCalendar, nyse_calendar
from prophetovol.reference.defaults import default_data_sources, default_underlyings
from prophetovol.reference.models import DataSource, Underlying
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
        """Close the service and its storage."""
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
