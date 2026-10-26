"""Time to expiry, settlement date, expiry and last trading day (CONV-1 to CONV-3).

These functions are the reference definitions. Ingest computes the same values in SQL for whole
files (DATA-13) and a test checks the two agree row by row; the synthetic data generator uses
these functions directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

from prophetovol.core.conventions import DAYS_PER_YEAR, MINUTES_PER_YEAR
from prophetovol.core.types import SettlementStyle

_ONE_MINUTE = timedelta(minutes=1)


class SessionCalendar(Protocol):
    """The part of a trading calendar these functions need (see ``reference.calendar``)."""

    def session_on_or_before(self, day: date) -> date:
        """Return the last trading day on or before ``day``.

        :param day: Any date.
        """

    def previous_session(self, day: date) -> date:
        """Return the last trading day strictly before ``day``.

        :param day: Any date.
        """

    def sessions_after_through(self, start: date, end: date) -> int:
        """Count trading days ``d`` with ``start < d <= end``.

        :param start: Exclusive lower bound.
        :param end: Inclusive upper bound.
        """


def local_datetime(day: date, clock: time) -> datetime:
    """Combine a date and a clock time into an exchange-local date-time without time zone.

    :param day: The date.
    :param clock: The exchange-local clock time, for example 16:15.
    :returns: A naive :class:`~datetime.datetime`.
    """
    return datetime.combine(day, clock)


def to_instant(local: datetime, tz_name: str) -> datetime:
    """Convert an exchange-local date-time to a UTC instant.

    :param local: A naive exchange-local date-time.
    :param tz_name: The exchange's IANA time zone, for example ``America/New_York``.
    :returns: The same moment as an aware UTC :class:`~datetime.datetime`.
    :raises ValueError: If ``local`` already carries a time zone.
    """
    if local.tzinfo is not None:
        raise ValueError("expected an exchange-local date-time without time zone")
    return local.replace(tzinfo=ZoneInfo(tz_name)).astimezone(timezone.utc)


def minutes_to_expiry(as_of_local: datetime, expiry_local: datetime) -> int:
    """Whole minutes from the as-of time to the expiry on the exchange clock (CONV-1).

    Both arguments are exchange-local and naive, so a daylight-saving change between them is
    ignored (CONV-1). Seconds, if any, are dropped (the difference is
    floored to whole minutes).

    :param as_of_local: The snapshot's as-of time, exchange-local, without time zone.
    :param expiry_local: The contract's expiry, exchange-local, without time zone.
    :returns: The minutes; negative when the expiry is before the as-of time.
    :raises ValueError: If either argument carries a time zone.
    """
    if as_of_local.tzinfo is not None or expiry_local.tzinfo is not None:
        raise ValueError("time to expiry is measured on the exchange clock: pass naive local date-times")
    return (expiry_local - as_of_local) // _ONE_MINUTE


def time_to_expiry_years(as_of_local: datetime, expiry_local: datetime) -> float:
    """Time to expiry as a year fraction: minutes on the exchange clock over minutes in 365 days (CONV-1).

    :param as_of_local: The snapshot's as-of time, exchange-local, without time zone.
    :param expiry_local: The contract's expiry, exchange-local, without time zone.
    :returns: The year fraction.
    """
    return minutes_to_expiry(as_of_local, expiry_local) / MINUTES_PER_YEAR


def days_to_expiry(time_to_expiry: float) -> float:
    """Fractional calendar days to expiry, for people (CONV-1).

    :param time_to_expiry: Time to expiry in years.
    :returns: ``time_to_expiry × 365``.
    """
    return time_to_expiry * DAYS_PER_YEAR


@dataclass(frozen=True)
class ExpiryDates:
    """When a contract settles, expires and last trades (CONV-3).

    :param settlement_date: The last trading day on or before the expiration date.
    :param last_trading_date: The trading day before the settlement date (AM) or the settlement date (PM).
    :param expiry_local: The settlement date at the settlement style's expiry time, exchange clock, naive.
    :param expiry_timestamp: The same moment as an aware UTC instant.
    """

    settlement_date: date
    last_trading_date: date
    expiry_local: datetime
    expiry_timestamp: datetime


def expiry_dates(expiration: date, settlement_style: SettlementStyle | str, expiry_time: time,
                 calendar: SessionCalendar, tz_name: str) -> ExpiryDates:
    """Derive the settlement date, expiry and last trading day of an expiration (CONV-3).

    An expiration dated on a trading day settles that day. One dated on a non-trading day (the
    Saturday-dated monthlies before 2015) settles on the last trading day before it. An AM-settled
    contract last trades on the trading day before its settlement date, which is when the engine
    force-closes it (SPEC-51); a PM-settled contract trades until it settles.

    :param expiration: The expiration date as the vendor gives it.
    :param settlement_style: ``AM`` or ``PM``.
    :param expiry_time: The exchange-local expiry time for that settlement style (09:30 or 16:00 for SPX).
    :param calendar: The trading calendar.
    :param tz_name: The exchange's IANA time zone.
    :returns: The derived dates and times.
    """
    style = SettlementStyle(settlement_style)
    settlement = calendar.session_on_or_before(expiration)
    last_trading = calendar.previous_session(settlement) if style is SettlementStyle.AM else settlement
    expiry_local = local_datetime(settlement, expiry_time)
    return ExpiryDates(settlement_date=settlement, last_trading_date=last_trading,
                       expiry_local=expiry_local, expiry_timestamp=to_instant(expiry_local, tz_name))


def trading_days_to_expiry(as_of_date: date, settlement_date: date, calendar: SessionCalendar) -> int:
    """Trading days after the as-of date up to and including the settlement date (CONV-2).

    :param as_of_date: The snapshot's date.
    :param settlement_date: The contract's settlement date.
    :param calendar: The trading calendar.
    :returns: The count; zero when the settlement date is not after the as-of date.
    """
    if settlement_date <= as_of_date:
        return 0
    return calendar.sessions_after_through(as_of_date, settlement_date)
