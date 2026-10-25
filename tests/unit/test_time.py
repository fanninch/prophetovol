"""TEST-5 (first part): time to expiry on the exchange clock; settlement date, expiry, last trading day."""

from datetime import date, datetime, time, timezone

import pytest

from prophetovol.core.types import SettlementStyle
from prophetovol.pricing.time import (days_to_expiry, expiry_dates, local_datetime, minutes_to_expiry,
                                      time_to_expiry_years, to_instant, trading_days_to_expiry)
from prophetovol.reference.calendar import nyse_calendar

NY = "America/New_York"
SNAP = time(16, 15)
AM, PM = time(9, 30), time(16, 0)


def years(minutes):
    return minutes / 525_600


class TestTimeToExpiry:
    def test_pm_weekly_one_day_out_is_fifteen_minutes_short(self):
        t = time_to_expiry_years(local_datetime(date(2024, 8, 29), SNAP), local_datetime(date(2024, 8, 30), PM))
        assert t == years(24 * 60 - 15)
        assert round(days_to_expiry(t), 2) == 0.99

    def test_am_expiry_next_morning(self):
        # Thursday 16:15 to Friday 09:30 = 17 h 15 min
        assert minutes_to_expiry(local_datetime(date(2024, 6, 20), SNAP), local_datetime(date(2024, 6, 21), AM)) == 1035

    def test_45_days_pm(self):
        t = time_to_expiry_years(local_datetime(date(2024, 1, 2), SNAP), local_datetime(date(2024, 2, 16), PM))
        assert t == years(45 * 1440 - 15)

    @pytest.mark.parametrize("as_of, expiry", [
        (date(2024, 3, 8), date(2024, 3, 11)),   # DST starts Sunday 2024-03-10
        (date(2024, 11, 1), date(2024, 11, 4)),  # DST ends Sunday 2024-11-03
    ])
    def test_dst_change_is_ignored(self, as_of, expiry):
        a, e = local_datetime(as_of, SNAP), local_datetime(expiry, PM)
        clock = minutes_to_expiry(a, e)
        assert clock == 3 * 1440 - 15  # the vendor's clock-time convention
        absolute = (to_instant(e, NY) - to_instant(a, NY)).total_seconds() / 60
        assert abs(absolute - clock) == 60  # instants would differ by exactly the DST hour

    def test_aware_datetimes_are_rejected(self):
        aware = datetime(2024, 1, 2, 16, 15, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="exchange clock"):
            minutes_to_expiry(aware, datetime(2024, 1, 3, 16, 0))

    def test_seconds_are_floored_and_past_expiry_is_negative(self):
        assert minutes_to_expiry(datetime(2024, 1, 2, 16, 15), datetime(2024, 1, 2, 16, 16, 59)) == 1
        assert minutes_to_expiry(datetime(2024, 1, 2, 16, 15), datetime(2024, 1, 2, 16, 0)) == -15

    def test_to_instant(self):
        assert to_instant(datetime(2024, 7, 1, 16, 0), NY) == datetime(2024, 7, 1, 20, 0, tzinfo=timezone.utc)
        assert to_instant(datetime(2024, 1, 2, 16, 0), NY) == datetime(2024, 1, 2, 21, 0, tzinfo=timezone.utc)


class TestExpiryDates:
    cal = nyse_calendar()

    def test_modern_friday_am_monthly(self):
        e = expiry_dates(date(2024, 6, 21), SettlementStyle.AM, AM, self.cal, NY)
        assert e.settlement_date == date(2024, 6, 21)
        assert e.last_trading_date == date(2024, 6, 20)  # Thursday
        assert e.expiry_local == datetime(2024, 6, 21, 9, 30)
        assert e.expiry_timestamp == datetime(2024, 6, 21, 13, 30, tzinfo=timezone.utc)

    def test_saturday_dated_am_monthly_settles_friday_and_closes_thursday(self):
        e = expiry_dates(date(2010, 3, 20), "AM", AM, self.cal, NY)  # Saturday
        assert e.settlement_date == date(2010, 3, 19)
        assert e.last_trading_date == date(2010, 3, 18)
        assert e.expiry_local == datetime(2010, 3, 19, 9, 30)

    def test_saturday_dated_when_friday_is_good_friday(self):
        e = expiry_dates(date(2008, 3, 22), "AM", AM, self.cal, NY)  # Good Friday 2008-03-21 closed
        assert e.settlement_date == date(2008, 3, 20)
        assert e.last_trading_date == date(2008, 3, 19)

    def test_pm_weekly_trades_until_it_settles(self):
        e = expiry_dates(date(2024, 8, 30), SettlementStyle.PM, PM, self.cal, NY)
        assert e.settlement_date == e.last_trading_date == date(2024, 8, 30)
        assert e.expiry_local == datetime(2024, 8, 30, 16, 0)

    def test_thursday_dated_holiday_expiration(self):
        # Good Friday 2024-03-29: the weekly was dated Thursday 2024-03-28
        e = expiry_dates(date(2024, 3, 28), "PM", PM, self.cal, NY)
        assert e.settlement_date == date(2024, 3, 28)


class TestTradingDaysToExpiry:
    cal = nyse_calendar()

    def test_counts_after_as_of_through_settlement(self):
        assert trading_days_to_expiry(date(2024, 8, 29), date(2024, 8, 30), self.cal) == 1

    def test_skips_weekends_and_holidays(self):
        # Wed 2024-07-03 to Mon 2024-07-08: Jul 4 is a holiday -> Fri 5 and Mon 8
        assert trading_days_to_expiry(date(2024, 7, 3), date(2024, 7, 8), self.cal) == 2

    def test_zero_on_or_after_settlement(self):
        assert trading_days_to_expiry(date(2024, 8, 30), date(2024, 8, 30), self.cal) == 0
        assert trading_days_to_expiry(date(2024, 9, 3), date(2024, 8, 30), self.cal) == 0
