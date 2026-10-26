"""The NYSE trading calendar wrapper (REF-10, REF-11)."""

from datetime import date
from importlib import metadata

import pytest

from prophetovol.core.errors import ConfigurationError
from prophetovol.reference.calendar import TradingCalendar, nyse_calendar


@pytest.fixture(scope="module")
def cal() -> TradingCalendar:
    return nyse_calendar()


def test_matches_the_vendor_files_session_count(cal):
    # Phase 0: the vendor files have exactly the 4,446 XNYS sessions from 2007-01-03 to 2024-08-30
    assert len(cal.sessions_in_range(date(2007, 1, 3), date(2024, 8, 30))) == 4446


@pytest.mark.parametrize("day", [date(2012, 10, 29), date(2012, 10, 30), date(2018, 12, 5), date(2025, 1, 9),
                                 date(2008, 3, 21), date(2024, 7, 4), date(2024, 8, 31)])
def test_closures_holidays_and_weekends_are_not_sessions(cal, day):
    assert not cal.is_session(day)


def test_lookups(cal):
    assert cal.is_session(date(2024, 8, 30))
    assert cal.session_on_or_before(date(2024, 8, 31)) == date(2024, 8, 30)
    assert cal.session_on_or_before(date(2024, 8, 30)) == date(2024, 8, 30)
    assert cal.previous_session(date(2024, 9, 3)) == date(2024, 8, 30)  # Labor Day Monday in between
    assert cal.next_session(date(2024, 8, 30)) == date(2024, 9, 3)
    assert cal.sessions_after_through(date(2024, 8, 29), date(2024, 9, 3)) == 2
    assert cal.sessions_after_through(date(2024, 9, 3), date(2024, 8, 29)) == 0


def test_covers_long_dated_expirations(cal):
    assert cal.session_on_or_before(date(2029, 12, 21)) == date(2029, 12, 21)


def test_out_of_range_is_an_error(cal):
    with pytest.raises(ConfigurationError, match="outside the trading calendar"):
        cal.is_session(date(1980, 1, 2))


def test_version_is_the_package_version(cal):
    assert cal.version == metadata.version("exchange_calendars") and cal.name == "XNYS"


def test_shared_instance_is_cached():
    assert nyse_calendar() is nyse_calendar()
