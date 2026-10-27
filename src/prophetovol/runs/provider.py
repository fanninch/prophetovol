"""Loading a run's market data ahead of the engine (plan §4.6, NFR-1).

The :class:`MarketDataProvider` is service-side: it reads the run's data in chunks of three months
of steps, one storage read per chunk, with the data versions captured at pre-flight (decision 30),
only the columns the engine uses and only expirations within the spec's horizon (decision 31). It
hands the engine one :class:`~prophetovol.engine.view.MarketDataView` per step, a zero-copy slice
of the chunk, and never itself.
"""

from __future__ import annotations

import math
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
import pyarrow as pa

from prophetovol.core.errors import ConfigurationError
from prophetovol.core.records import DataVersionRecord
from prophetovol.engine.schedule import Step, StepSchedule
from prophetovol.engine.view import ENGINE_COLUMNS, MarketDataView
from prophetovol.registry.params.selection import SameAsLegParams, TargetDaysParams, TradingDaysOutParams
from prophetovol.storage.adapter import StorageAdapter
from prophetovol.strategy.model import StrategySpec

CHUNK_MONTHS = 3
"""Months of steps read at once (decision 15)."""

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _trading_to_calendar_days(trading_days: int) -> float:
    """A safe upper bound on the calendar days spanned by a number of trading days.

    Five trading days span at most seven calendar days; four more days cover holidays, and one more
    the fraction of a day to the expiry time.

    :param trading_days: Trading days.
    :returns: Calendar days.
    """
    return math.ceil(trading_days / 5) * 7 + 5


def spec_horizon_days(spec: StrategySpec) -> float | None:
    """The most calendar days to expiry any of the spec's legs can select (decision 31).

    Held contracts stay within it, because their days to expiry only fall, and a roll re-selects with
    the same selectors.

    :param spec: A valid spec.
    :returns: The horizon in calendar days, or None when a selector has no bound (``nth_expiration``,
        ``next_after_leg``), so every expiration must be read.
    """
    horizons: dict[str, float | None] = {}

    def leg_horizon(leg_id: str) -> float | None:
        """The horizon of one leg, following same_as_leg references.

        :param leg_id: The leg.
        :returns: Its horizon, or None when unbounded.
        """
        if leg_id not in horizons:
            selector = spec.leg(leg_id).expiration
            if isinstance(selector, TargetDaysParams):
                horizons[leg_id] = selector.window()[1]
            elif isinstance(selector, TradingDaysOutParams):
                horizons[leg_id] = _trading_to_calendar_days(selector.n + selector.tolerance)
            elif isinstance(selector, SameAsLegParams):
                horizons[leg_id] = leg_horizon(selector.leg)
            else:  # nth_expiration, next_after_leg, or a selector added later without a known bound
                horizons[leg_id] = None
        return horizons[leg_id]

    values = [leg_horizon(leg.id) for leg in spec.legs]
    return None if any(v is None for v in values) else max(values)


@dataclass
class ProviderStats:
    """What the provider read, for the run-time measurement (NFR-1).

    :param chunks: Chunks read.
    :param rows: Rows read.
    :param read_seconds: Time spent reading, in seconds.
    """

    chunks: int = 0
    rows: int = 0
    read_seconds: float = 0.0


class MarketDataProvider:
    """Loads a run's market data in chunks and yields one view per step (plan §4.6).

    :param storage: The storage adapter.
    :param underlying: The run's underlying.
    :param schedule: The run's step schedule, from pre-flight.
    :param versions: The data version each step reads, in step order (decision 30).
    :param horizon_days: Only expirations at most this many calendar days away; None reads every one.
    :param columns: The columns to load.
    :param chunk_months: Months of steps per read.
    """

    def __init__(self, storage: StorageAdapter, underlying: str, schedule: StepSchedule,
                 versions: list[DataVersionRecord], horizon_days: float | None = None,
                 columns: tuple[str, ...] = ENGINE_COLUMNS, chunk_months: int = CHUNK_MONTHS) -> None:
        if len(versions) != len(schedule.steps):
            raise ConfigurationError(f"{len(schedule.steps)} steps but {len(versions)} data versions")
        for step, version in zip(schedule.steps, versions):
            if version.as_of != step.as_of:
                raise ConfigurationError(f"step {step.seq} is as of {step.as_of}, its data version as of {version.as_of}")
        self._storage = storage
        self._underlying = underlying
        self._steps = schedule.steps
        self._versions = versions
        self._horizon = horizon_days
        self._columns = list(columns)
        self._chunk_months = chunk_months
        self.stats = ProviderStats()

    def _chunks(self) -> Iterator[list[int]]:
        """Group step indexes into chunks of ``chunk_months`` calendar months from the first step.

        :returns: Lists of step indexes, in order.
        """
        if not self._steps:
            return
        first = self._steps[0].day.year * 12 + self._steps[0].day.month - 1
        current: list[int] = []
        current_key = 0
        for i, step in enumerate(self._steps):
            key = (step.day.year * 12 + step.day.month - 1 - first) // self._chunk_months
            if current and key != current_key:
                yield current
                current = []
            current_key = key
            current.append(i)
        if current:
            yield current

    def views(self) -> Iterator[MarketDataView]:
        """One view per step, in step order; each chunk is read when its first step is reached.

        :returns: The views.
        """
        for indexes in self._chunks():
            versions = [self._versions[i] for i in indexes]
            started = time.perf_counter()
            rows = self._storage.read_market_chunk(self._underlying, versions, self._columns, self._horizon)
            levels = self._storage.read_index_levels(self._underlying, versions)
            self.stats.chunks += 1
            self.stats.rows += rows.num_rows
            self.stats.read_seconds += time.perf_counter() - started
            stamps = _microseconds(rows)
            for i in indexes:
                step: Step = self._steps[i]
                key = (step.as_of - _EPOCH) // timedelta(microseconds=1)
                lo, hi = np.searchsorted(stamps, key, "left"), np.searchsorted(stamps, key, "right")
                yield MarketDataView(step=step.seq, as_of=step.as_of, as_of_date=step.day,
                                     index_level=levels[step.as_of], rows=rows.slice(int(lo), int(hi - lo)))


def _microseconds(rows: pa.Table) -> np.ndarray:
    """The rows' as-of instants as microseconds since the epoch, for slicing by step.

    :param rows: Rows sorted by ``as_of``.
    :returns: An int64 array.
    """
    if rows.num_rows == 0:
        return np.array([], dtype=np.int64)
    column = rows.column("as_of").cast(pa.timestamp("us", tz="UTC"))
    return column.to_numpy().astype("datetime64[us]").astype(np.int64)
