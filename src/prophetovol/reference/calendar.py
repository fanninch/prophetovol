"""The trading calendar: the NYSE calendar from ``exchange_calendars`` (REF-10, REF-11).

The sessions are loaded once for a fixed range and held as a sorted array, so every lookup is a
binary search and the result never depends on today's date.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from importlib import metadata

import exchange_calendars
import numpy as np

from prophetovol.core.errors import ConfigurationError

CALENDAR_NAME = "XNYS"
"""The ``exchange_calendars`` code of the New York Stock Exchange calendar."""

FIRST_DAY = date(1990, 1, 2)
"""First date the calendar covers."""

LAST_DAY = date(2040, 12, 31)
"""Last date the calendar covers (beyond the longest listed expirations)."""


class TradingCalendar:
    """Trading days of one exchange, with the lookups the engine and ingest need.

    :param name: The ``exchange_calendars`` calendar code.
    :param first_day: First date covered.
    :param last_day: Last date covered.
    """

    def __init__(self, name: str = CALENDAR_NAME, first_day: date = FIRST_DAY, last_day: date = LAST_DAY) -> None:
        cal = exchange_calendars.get_calendar(name, start=first_day.isoformat(), end=last_day.isoformat())
        self.name = name
        self.first_day = first_day
        self.last_day = last_day
        self._sessions = np.array([s.date() for s in cal.sessions], dtype="datetime64[D]")

    @property
    def version(self) -> str:
        """The calendar's version: the installed ``exchange_calendars`` version (REF-11)."""
        return metadata.version("exchange_calendars")

    def _check(self, day: date) -> np.datetime64:
        """Validate that ``day`` is covered and convert it for searching.

        :param day: The date to check.
        :returns: The date as ``datetime64[D]``.
        :raises ConfigurationError: If the date is outside the calendar's range.
        """
        if not self.first_day <= day <= self.last_day:
            raise ConfigurationError(
                f"{day} is outside the trading calendar's range {self.first_day} to {self.last_day}")
        return np.datetime64(day, "D")

    @staticmethod
    def _to_date(value: np.datetime64) -> date:
        """Convert a ``datetime64[D]`` back to a :class:`~datetime.date`.

        :param value: The value to convert.
        :returns: The date.
        """
        return value.astype("datetime64[D]").item()

    def is_session(self, day: date) -> bool:
        """Whether ``day`` is a trading day.

        :param day: The date.
        :returns: ``True`` for a trading day.
        """
        d = self._check(day)
        i = np.searchsorted(self._sessions, d)
        return bool(i < len(self._sessions) and self._sessions[i] == d)

    def sessions_in_range(self, start: date, end: date) -> list[date]:
        """Trading days from ``start`` to ``end``, both inclusive.

        :param start: First date.
        :param end: Last date.
        :returns: The trading days, in order.
        """
        lo = np.searchsorted(self._sessions, self._check(start), side="left")
        hi = np.searchsorted(self._sessions, self._check(end), side="right")
        return [self._to_date(s) for s in self._sessions[lo:hi]]

    def session_on_or_before(self, day: date) -> date:
        """The last trading day on or before ``day``.

        :param day: Any date.
        :returns: The trading day.
        """
        i = np.searchsorted(self._sessions, self._check(day), side="right") - 1
        if i < 0:
            raise ConfigurationError(f"no trading day on or before {day} in the calendar")
        return self._to_date(self._sessions[i])

    def previous_session(self, day: date) -> date:
        """The last trading day strictly before ``day``.

        :param day: Any date.
        :returns: The trading day.
        """
        i = np.searchsorted(self._sessions, self._check(day), side="left") - 1
        if i < 0:
            raise ConfigurationError(f"no trading day before {day} in the calendar")
        return self._to_date(self._sessions[i])

    def next_session(self, day: date) -> date:
        """The first trading day strictly after ``day``.

        :param day: Any date.
        :returns: The trading day.
        """
        i = np.searchsorted(self._sessions, self._check(day), side="right")
        if i >= len(self._sessions):
            raise ConfigurationError(f"no trading day after {day} in the calendar")
        return self._to_date(self._sessions[i])

    def sessions_after_through(self, start: date, end: date) -> int:
        """Count trading days ``d`` with ``start < d <= end`` (zero when ``end <= start``).

        :param start: Exclusive lower bound.
        :param end: Inclusive upper bound.
        :returns: The count.
        """
        lo = np.searchsorted(self._sessions, self._check(start), side="right")
        hi = np.searchsorted(self._sessions, self._check(end), side="right")
        return max(0, int(hi - lo))


@lru_cache(maxsize=None)
def nyse_calendar() -> TradingCalendar:
    """The shared NYSE calendar, loaded once per process.

    :returns: The calendar covering 1990 to 2040.
    """
    return TradingCalendar()
