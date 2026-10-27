"""The engine's only window onto market data: one step's snapshot, guarded by its as-of time (ARC-3).

A :class:`MarketDataView` holds a zero-copy slice of one step's rows, in the columns the engine
uses (:data:`ENGINE_COLUMNS`). Every method takes an optional as-of time and raises
:class:`~prophetovol.core.errors.PointInTimeError` for anything stamped after the view's own, so
the engine cannot read the future even by mistake (TEST-4). The engine receives views one at a
time and never the provider that loads them (plan §4.6).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import numpy as np
import pyarrow as pa

from prophetovol.core.errors import PointInTimeError

ENGINE_COLUMNS: tuple[str, ...] = (
    "as_of", "as_of_date", "osi_symbol", "vendor_symbol", "vendor_root", "root", "settlement_style", "expiration",
    "settlement_date", "expiry_timestamp", "last_trading_date", "time_to_expiry_years", "days_to_expiry",
    "trading_days_to_expiry", "strike", "option_type", "bid", "ask", "iv", "forward", "forward_source", "delta",
    "gamma", "vega", "theta", "open_interest", "vendor_flag",
)
"""The market snapshot columns the engine reads: selection, marking, greeks and the position snapshot's
identity fields (RES-1). The index level comes with each view separately."""


@dataclass(frozen=True)
class ExpirationInfo:
    """One listed expiration of one root in a view, with what selectors need to know about it.

    :param root: The normalized root, for example ``SPXW``.
    :param expiration: The expiration date as listed.
    :param settlement_style: ``AM`` or ``PM``.
    :param settlement_date: The settlement date (CONV-3).
    :param last_trading_date: The last trading day (CONV-3).
    :param expiry_timestamp: The expiry instant (UTC).
    :param days_to_expiry: Fractional calendar days to expiry at the view's as-of time (CONV-1).
    :param trading_days_to_expiry: Trading days to expiry (CONV-2).
    :param contracts: Rows listed for it in the view.
    """

    root: str
    expiration: date
    settlement_style: str
    settlement_date: date
    last_trading_date: date
    expiry_timestamp: datetime
    days_to_expiry: float
    trading_days_to_expiry: int
    contracts: int


class MarketDataView:
    """One step's market snapshot, read-only and bound to the step's as-of time (ARC-3).

    :param step: The step's number.
    :param as_of: The step's as-of instant (aware, UTC).
    :param as_of_date: The step's trading day.
    :param index_level: The index level of the snapshot (the PM settlement value on expiration dates).
    :param rows: The step's rows, in :data:`ENGINE_COLUMNS` (or a subset), all stamped ``as_of``.
    """

    __slots__ = ("_step", "_as_of", "_as_of_date", "_index_level", "_rows", "_by_symbol", "_expirations")

    def __init__(self, step: int, as_of: datetime, as_of_date: date, index_level: float, rows: pa.Table) -> None:
        if as_of.tzinfo is None:
            raise ValueError("a view's as-of time must be timezone-aware")
        self._step = step
        self._as_of = as_of
        self._as_of_date = as_of_date
        self._index_level = index_level
        self._rows = rows
        self._by_symbol: dict[str, int] | None = None
        self._expirations: list[ExpirationInfo] | None = None

    @property
    def step(self) -> int:
        """The step's number."""
        return self._step

    @property
    def as_of(self) -> datetime:
        """The step's as-of instant (UTC)."""
        return self._as_of

    @property
    def as_of_date(self) -> date:
        """The step's trading day."""
        return self._as_of_date

    @property
    def index_level(self) -> float:
        """The snapshot's index level."""
        return self._index_level

    def __len__(self) -> int:
        """The number of rows in the view."""
        return self._rows.num_rows

    def _check(self, as_of: datetime | None) -> None:
        """Refuse any request stamped after the view's as-of time (ARC-3).

        :param as_of: The requested as-of time; None means the view's own.
        :raises PointInTimeError: If it is later than the view's.
        """
        if as_of is None:
            return
        if as_of.tzinfo is None:
            raise ValueError("as-of times must be timezone-aware")
        if as_of > self._as_of:
            raise PointInTimeError(f"step {self._step} is as of {self._as_of.isoformat()}; data as of "
                                   f"{as_of.isoformat()} is in its future")

    def table(self, as_of: datetime | None = None) -> pa.Table:
        """The step's rows.

        :param as_of: The as-of time the caller asks for; None means the view's own.
        :returns: The rows, a zero-copy slice.
        :raises PointInTimeError: If ``as_of`` is after the view's.
        """
        self._check(as_of)
        return self._rows

    def column(self, name: str, as_of: datetime | None = None) -> np.ndarray:
        """One column of the step's rows as a NumPy array (nulls as NaN or None).

        :param name: The column, one of :data:`ENGINE_COLUMNS`.
        :param as_of: The as-of time the caller asks for; None means the view's own.
        :returns: The values, in row order.
        :raises PointInTimeError: If ``as_of`` is after the view's.
        """
        self._check(as_of)
        return self._rows.column(name).to_numpy(zero_copy_only=False)

    def contract(self, osi_symbol: str, as_of: datetime | None = None) -> dict[str, Any] | None:
        """One contract's row, by its OSI symbol (DATA-2).

        :param osi_symbol: The contract's OSI symbol.
        :param as_of: The as-of time the caller asks for; None means the view's own.
        :returns: The row as a dict, or None when the contract is not in the snapshot.
        :raises PointInTimeError: If ``as_of`` is after the view's.
        """
        self._check(as_of)
        if self._by_symbol is None:
            self._by_symbol = {s: i for i, s in enumerate(self._rows.column("osi_symbol").to_pylist())}
        i = self._by_symbol.get(osi_symbol)
        return None if i is None else self._rows.slice(i, 1).to_pylist()[0]

    def expirations(self, as_of: datetime | None = None) -> list[ExpirationInfo]:
        """The listed expirations per root, ordered by expiry, then root.

        :param as_of: The as-of time the caller asks for; None means the view's own.
        :returns: One entry per (root, expiration).
        :raises PointInTimeError: If ``as_of`` is after the view's.
        """
        self._check(as_of)
        if self._expirations is None:
            self._expirations = group_expirations(self._rows)
        return list(self._expirations)


def group_expirations(rows: pa.Table) -> list[ExpirationInfo]:
    """The expirations listed in some rows of one snapshot, one per (root, expiration).

    :param rows: Rows of one as-of time, with the expiration columns of :data:`ENGINE_COLUMNS`.
    :returns: The expirations, ordered by expiry, then root.
    """
    if rows.num_rows == 0:
        return []
    keys = ["root", "expiration"]
    firsts = ["settlement_style", "settlement_date", "last_trading_date", "expiry_timestamp", "days_to_expiry",
              "trading_days_to_expiry"]
    grouped = rows.select(keys + firsts).group_by(keys, use_threads=False).aggregate(
        [(c, "min") for c in firsts] + [("root", "count")])
    return sorted(
        (ExpirationInfo(root=r["root"], expiration=r["expiration"], settlement_style=r["settlement_style_min"],
                        settlement_date=r["settlement_date_min"], last_trading_date=r["last_trading_date_min"],
                        expiry_timestamp=r["expiry_timestamp_min"], days_to_expiry=r["days_to_expiry_min"],
                        trading_days_to_expiry=r["trading_days_to_expiry_min"], contracts=r["root_count"])
         for r in grouped.to_pylist()),
        key=lambda e: (e.expiry_timestamp, e.root))
