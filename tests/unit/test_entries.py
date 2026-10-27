"""Entry schedules (SPEC-30 to SPEC-35) on the NYSE calendar, around Good Friday (Mar 29, 2024)."""

from __future__ import annotations

from datetime import date

import pytest

from prophetovol.engine.entries import EntryState
from prophetovol.reference.calendar import nyse_calendar
from prophetovol.registry.catalog import ENTRY_SCHEDULES, all_registries

CAL = nyse_calendar()
FIRST = date(2024, 3, 25)  # a Monday


def schedule(name: str, **params):
    all_registries()
    impl = ENTRY_SCHEDULES.get(name)
    return impl.target(impl.params.model_validate({"schedule": name} | params))


def state(day, open_structures=0, opened_any=False, last_close_day=None, first_day=FIRST):
    return EntryState(day=day, first_day=first_day, open_structures=open_structures, opened_any=opened_any,
                      last_close_day=last_close_day)


def test_once_until_a_structure_opens():
    once = schedule("once")
    assert once.due(state(FIRST), CAL)
    assert once.due(state(date(2024, 3, 26)), CAL)  # selection failed on the first step: retried
    assert not once.due(state(date(2024, 3, 27), opened_any=True), CAL)


class TestWhenFlat:
    def test_flat_and_max_open(self):
        flat = schedule("when_flat")
        assert flat.due(state(FIRST), CAL) and not flat.due(state(FIRST, open_structures=1), CAL)
        two = schedule("when_flat", max_open=2)
        assert two.due(state(FIRST, open_structures=1), CAL) and not two.due(state(FIRST, open_structures=2), CAL)

    @pytest.mark.parametrize("cooldown, closed, day, due", [
        (1, date(2024, 4, 1), date(2024, 4, 1), False),   # never re-enter at the closing step by default
        (1, date(2024, 4, 1), date(2024, 4, 2), True),
        (0, date(2024, 4, 1), date(2024, 4, 1), True),
        (2, date(2024, 4, 1), date(2024, 4, 2), False),
        (2, date(2024, 4, 1), date(2024, 4, 3), True),
        (1, date(2024, 3, 28), date(2024, 4, 1), True),   # Good Friday is not a trading day: one trading day later
        (2, date(2024, 3, 28), date(2024, 4, 1), False),
    ])
    def test_cooldown_in_trading_days(self, cooldown, closed, day, due):
        assert schedule("when_flat", cooldown_trading_days=cooldown).due(state(day, last_close_day=closed), CAL) is due


class TestEveryNTradingDays:
    @pytest.mark.parametrize("day, due", [
        (date(2024, 3, 25), True),   # the first step: 0 trading days
        (date(2024, 3, 28), False),  # 3
        (date(2024, 4, 1), False),   # 4: Good Friday does not count
        (date(2024, 4, 2), True),    # 5
        (date(2024, 4, 9), True),    # 10
    ])
    def test_counted_on_the_calendar(self, day, due):
        assert schedule("every_n_trading_days", n=5).due(state(day), CAL) is due

    def test_max_open(self):
        every = schedule("every_n_trading_days", n=5, max_open=2)
        assert every.due(state(date(2024, 4, 2), open_structures=1), CAL)
        assert not every.due(state(date(2024, 4, 2), open_structures=2), CAL)


class TestWeekdays:
    def test_listed_days(self):
        mondays = schedule("weekdays", weekdays=["MON", "WED"])
        assert mondays.due(state(date(2024, 4, 1)), CAL) and mondays.due(state(date(2024, 4, 3)), CAL)
        assert not mondays.due(state(date(2024, 4, 2)), CAL)
        assert not mondays.due(state(date(2024, 4, 1), open_structures=1), CAL)

    @pytest.mark.parametrize("shift, day, due", [
        ("skip", date(2024, 4, 1), False),  # Friday Mar 29 was Good Friday: skipped
        ("next", date(2024, 4, 1), True),   # moved to the next trading day
        ("next", date(2024, 4, 2), False),
    ])
    def test_holiday_shift(self, shift, day, due):
        fridays = schedule("weekdays", weekdays=["FRI"], holiday_shift=shift)
        assert fridays.due(state(day), CAL) is due

    def test_monday_holiday_moves_to_tuesday(self):
        mondays = schedule("weekdays", weekdays=["MON"], holiday_shift="next")
        # Memorial Day, Monday May 27, 2024
        assert mondays.due(state(date(2024, 5, 28), first_day=date(2024, 5, 1)), CAL)
        assert not mondays.due(state(date(2024, 5, 28), first_day=date(2024, 5, 28)), CAL)  # before the run began
