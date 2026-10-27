"""Entry schedules: when a spec opens a new structure (SPEC-30 to SPEC-35).

Each schedule answers :meth:`due` at a step from an :class:`EntryState`. A due entry whose selection
fails is simply due again at the next step the schedule allows; nothing is queued (SPEC-35). Trading
days are counted on the calendar, never in steps (ENG-4), so a skipped missing day counts as a
trading day but has no step and so no entry. A roll re-establishes a structure through its trigger,
not through the schedule, so it never waits for a cooldown.

The implementations are registered here with their parameter models (decision 29).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

from prophetovol.registry.catalog import ENTRY_SCHEDULES
from prophetovol.registry.params.schedules import (EveryNTradingDaysParams, HolidayShift, OnceParams,
                                                   WeekdaysParams, WhenFlatParams)
from prophetovol.registry.params.selection import Weekday

_WEEKDAYS = list(Weekday)


class EntryCalendar(Protocol):
    """The trading-calendar lookups the schedules need (``reference.calendar.TradingCalendar`` has them)."""

    def is_session(self, day: date) -> bool:
        """Whether ``day`` is a trading day.

        :param day: The date.
        """

    def previous_session(self, day: date) -> date:
        """The last trading day strictly before ``day``.

        :param day: The date.
        """

    def sessions_after_through(self, start: date, end: date) -> int:
        """Count trading days ``d`` with ``start < d <= end``.

        :param start: Exclusive lower bound.
        :param end: Inclusive upper bound.
        """


@dataclass(frozen=True)
class EntryState:
    """What a schedule needs to know about the run and the spec's structures at a step.

    :param day: The step's trading day.
    :param first_day: The run's first step day.
    :param open_structures: Structures of the spec open now.
    :param opened_any: Whether any structure has been opened by an entry so far.
    :param last_close_day: The last day a structure was closed by a close action or by expiry; None if never.
        Rolls do not count (SPEC-31).
    """

    day: date
    first_day: date
    open_structures: int
    opened_any: bool
    last_close_day: date | None = None


@ENTRY_SCHEDULES.register(
    "once", params=OnceParams, version="1",
    description="Opens one structure at the first step of the run. If selection fails there, it is retried at the "
                "next step until one opens.")
class Once:
    """The ``once`` entry schedule (SPEC-30).

    :param params: Its validated parameters.
    """

    def __init__(self, params: OnceParams) -> None:
        self.params = params

    def due(self, state: EntryState, calendar: EntryCalendar) -> bool:
        """Whether an entry is due at this step.

        :param state: The run's state at the step.
        :param calendar: The trading calendar.
        :returns: True until a structure has been opened.
        """
        return not state.opened_any


@ENTRY_SCHEDULES.register(
    "when_flat", params=WhenFlatParams, version="1",
    description="Opens a structure at any step when fewer than max_open structures of this spec are open (by default "
                "when none is), waiting cooldown_trading_days after a close by a close action or by expiry. A roll "
                "re-establishes the structure immediately, without the cooldown.")
class WhenFlat:
    """The ``when_flat`` entry schedule (SPEC-31).

    :param params: Its validated parameters.
    """

    def __init__(self, params: WhenFlatParams) -> None:
        self.params = params

    def due(self, state: EntryState, calendar: EntryCalendar) -> bool:
        """Whether an entry is due at this step.

        :param state: The run's state at the step.
        :param calendar: The trading calendar.
        :returns: True when below ``max_open`` and the cooldown since the last close has passed.
        """
        if state.open_structures >= self.params.max_open:
            return False
        if state.last_close_day is None:
            return True
        return calendar.sessions_after_through(state.last_close_day, state.day) >= self.params.cooldown_trading_days


@ENTRY_SCHEDULES.register(
    "every_n_trading_days", params=EveryNTradingDaysParams, version="1",
    description="Opens a structure every n trading days from the run's first step, counted on the trading calendar, "
                "while fewer than max_open structures of this spec are open.")
class EveryNTradingDays:
    """The ``every_n_trading_days`` entry schedule (SPEC-32).

    :param params: Its validated parameters.
    """

    def __init__(self, params: EveryNTradingDaysParams) -> None:
        self.params = params

    def due(self, state: EntryState, calendar: EntryCalendar) -> bool:
        """Whether an entry is due at this step.

        :param state: The run's state at the step.
        :param calendar: The trading calendar.
        :returns: True on the first step and every n-th trading day after it, below ``max_open``.
        """
        if state.open_structures >= self.params.max_open:
            return False
        return calendar.sessions_after_through(state.first_day, state.day) % self.params.n == 0


@ENTRY_SCHEDULES.register(
    "weekdays", params=WeekdaysParams, version="1",
    description="Opens a structure on the listed weekdays while fewer than max_open structures of this spec are "
                "open. When a listed day is not a trading day, holiday_shift skips it (default) or moves the entry "
                "to the next trading day.")
class Weekdays:
    """The ``weekdays`` entry schedule (SPEC-33).

    :param params: Its validated parameters.
    """

    def __init__(self, params: WeekdaysParams) -> None:
        self.params = params

    def due(self, state: EntryState, calendar: EntryCalendar) -> bool:
        """Whether an entry is due at this step.

        :param state: The run's state at the step.
        :param calendar: The trading calendar.
        :returns: True on a listed weekday, or with ``holiday_shift: next`` on the first trading day after a listed
            weekday that was not a trading day; below ``max_open``.
        """
        if state.open_structures >= self.params.max_open:
            return False
        listed = set(self.params.weekdays)
        if _WEEKDAYS[state.day.weekday()] in listed:
            return True
        if self.params.holiday_shift is not HolidayShift.NEXT or state.day <= state.first_day:
            return False
        previous = calendar.previous_session(state.day)
        day = previous + timedelta(days=1)
        while day < state.day:
            if _WEEKDAYS[day.weekday()] in listed and not calendar.is_session(day):
                return True
            day += timedelta(days=1)
        return False
