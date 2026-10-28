"""Selection (TEST-1, selection part): eligibility, filters, every selector, atomic multi-leg selection.

The views come from :func:`prophetovol.testdata.golden.selection_chain` after the ordinary ingest.
Expected values are worked out by hand in the comments; days to expiry are from the 16:15 ET
snapshot, for example 0.98958 days to a next-day 16:00 expiry.
"""

from __future__ import annotations

import copy
from datetime import date, datetime, timezone

import numpy as np
import pyarrow as pa
import pytest

from prophetovol.core.context import CallContext
from prophetovol.engine.selection import (eligible_rows, is_standard_monthly, passes_filter, select_legs,
                                          usual_spacing)
from prophetovol.engine.view import ENGINE_COLUMNS, ExpirationInfo, MarketDataView
from prophetovol.reference.calendar import nyse_calendar
from prophetovol.registry.params.selection import ExpirationFilter
from prophetovol.runs.service import BacktestService
from prophetovol.strategy.io import example_specs
from prophetovol.strategy.model import StrategySpec
from prophetovol.testdata.golden import SELECTION_DAYS, selection_chain, write_rows

CTX = CallContext.for_channel("library")
CAL = nyse_calendar()
MAR27, MAR28, APR1, APR18, APR19 = SELECTION_DAYS


@pytest.fixture(scope="module")
def views(tmp_path_factory) -> dict[date, MarketDataView]:
    folder = tmp_path_factory.mktemp("selection")
    path = write_rows(selection_chain().rows, folder / "selection.csv")
    out = {}
    with BacktestService.open(folder / "home") as svc:
        job = svc.import_files([path], CTX)
        svc.commit_import(job.result["import_id"], "replace", CTX)
        for v in svc.data_versions("SPX"):
            table = svc.storage.read_active_snapshot("SPX", v.as_of, [*ENGINE_COLUMNS, "index_level"])
            table = table.sort_by([("root", "ascending"), ("expiration", "ascending"), ("option_type", "ascending"),
                                   ("strike", "ascending")])
            out[v.as_of_date] = MarketDataView(1, v.as_of, v.as_of_date, table.column("index_level")[0].as_py(),
                                               table.drop(["index_level"]))
    return out


def spec(*legs, selection=None) -> StrategySpec:
    body = {"id": "t", "underlying": "SPX", "legs": list(legs), "entry": {"schedule": "when_flat"},
            "sizing": {"method": "contracts", "quantity": 1}}
    if selection:
        body["selection"] = selection
    return StrategySpec.model_validate(body)


def leg(leg_id="a", option_type="call", expiration=None, strike=None, **extra) -> dict:
    return {"id": leg_id, "option_type": option_type, "side": "short",
            "expiration": expiration or {"selector": "target_days", "days": 45},
            "strike": strike or {"selector": "atm"}, **extra}


def pick(view, *legs, selection=None, **kw):
    return select_legs(spec(*legs, selection=selection), view, CAL, **kw)


def chosen(view, expiration, strike=None, option_type="call"):
    result = pick(view, leg(option_type=option_type, expiration=expiration, strike=strike))
    assert result.ok, result.failure
    c = result.contracts["a"]
    return c.root, c.expiration, c.strike


class TestExpirationSelectors:
    def test_target_days(self, views):
        # 35–55 days: only SPX May 17 (50.72 days)
        assert chosen(views[MAR27], {"selector": "target_days", "days": 45})[:2] == ("SPX", date(2024, 5, 17))
        # Appendix B's same-day example: SPXW Mar 28 is 0.99 days out
        zero_dte = {"selector": "target_days", "days": 0.5, "max_days": 1}
        assert chosen(views[MAR27], zero_dte)[:2] == ("SPXW", date(2024, 3, 28))
        failed = pick(views[MAR28], leg(expiration=zero_dte))  # next is Apr 1, 3.99 days out
        assert failed.failure.selector == "expiration_selector target_days"
        assert failed.failure.message == ("no eligible expiration within 0 to 1 calendar days to expiry "
                                          "(nearest eligible: SPXW 2024-04-01 (3.99 days, 1 trading day); none earlier)")

    def test_a_gap_names_the_nearest_expiration_on_each_side(self, views):
        # 60 to 80 days from Mar 27: nothing; May 17 (50.72) is short of it, Jun 21 (85.72) beyond it
        failed = pick(views[MAR27], leg(expiration={"selector": "target_days", "days": 70}))
        assert failed.failure.message == (
            "no eligible expiration within 60 to 80 calendar days to expiry (nearest eligible: SPX 2024-05-17 "
            "(50.72 days, 36 trading days) and SPX 2024-06-21 (85.72 days, 59 trading days))")
        # past the chain's last expiration, Jun 21: a later one may exist beyond what the run reads (decision 31)
        failed = pick(views[MAR27], leg(expiration={"selector": "target_days", "days": 200}))
        assert failed.failure.message.endswith(
            "(nearest eligible: SPX 2024-06-21 (85.72 days, 59 trading days); none later among the expirations "
            "the run reads)")

    def test_default_window_is_floored_at_zero(self, views):
        # days 5: window 0–15; Apr 1 (4.99) is nearest
        assert chosen(views[MAR27], {"selector": "target_days", "days": 5})[:2] == ("SPXW", date(2024, 4, 1))

    def test_ties_follow_tie_break(self, views):
        by_date = {e.expiration: e.days_to_expiry for e in views[MAR27].expirations()}
        midway = by_date[date(2024, 4, 3)] + 1.0  # exactly between Apr 3 (6.99) and Apr 5 (8.99)
        later = {"selector": "target_days", "days": midway}
        assert chosen(views[MAR27], later)[1] == date(2024, 4, 5)
        assert chosen(views[MAR27], later | {"tie_break": "earlier"})[1] == date(2024, 4, 3)

    def test_trading_days_out(self, views):
        dailies = {"selector": "trading_days_out", "n": 1, "filter": {"settlement_styles": ["PM"]}}
        assert chosen(views[MAR27], dailies)[1] == date(2024, 3, 28)
        assert chosen(views[MAR28], dailies)[1] == date(2024, 4, 1)  # Good Friday is not a trading day
        # from Mar 27, trading days to expiry are 1, 2, 4, 6, …: none is 3, two are 1 away
        failed = pick(views[MAR27], leg(expiration={"selector": "trading_days_out", "n": 3}))
        assert failed.failure.message == (
            "no eligible expiration 3 trading day(s) out (tolerance 0; nearest eligible: SPXW 2024-04-01 "
            "(4.99 days, 2 trading days) and SPXW 2024-04-03 (6.99 days, 4 trading days))")
        tolerant = {"selector": "trading_days_out", "n": 3, "tolerance": 1}
        assert chosen(views[MAR27], tolerant)[1] == date(2024, 4, 3)
        assert chosen(views[MAR27], tolerant | {"tie_break": "earlier"})[1] == date(2024, 4, 1)

    def test_nth_expiration_across_a_weekend_and_a_holiday(self, views):
        # Thursday Mar 28 at 16:15: that day's 16:00 expiry has passed; next is Monday Apr 1, after Good Friday
        assert chosen(views[MAR28], {"selector": "nth_expiration", "n": 1})[1] == date(2024, 4, 1)
        assert chosen(views[MAR28], {"selector": "nth_expiration", "n": 2})[1] == date(2024, 4, 3)
        mondays = {"selector": "nth_expiration", "n": 2, "filter": {"weekdays": ["MON"]}}
        assert chosen(views[MAR27], mondays)[1] == date(2024, 4, 22)

    def test_nth_standard_monthly(self, views):
        monthly = {"selector": "nth_expiration", "n": 2, "filter": {"standard_monthly_only": True}}
        # by date, whatever the root: SPX Apr 19 (AM, 09:30), SPXW Apr 19 (PM, 16:00), SPX May 17, SPX Jun 21
        assert chosen(views[MAR27], monthly)[:2] == ("SPXW", date(2024, 4, 19))
        am = copy.deepcopy(monthly)
        am["filter"]["settlement_styles"] = ["AM"]
        assert chosen(views[MAR27], am)[:2] == ("SPX", date(2024, 5, 17))

    def test_am_monthly_is_not_eligible_on_its_last_trading_day(self, views):
        first_monthly = {"selector": "nth_expiration", "n": 1, "filter": {"standard_monthly_only": True}}
        assert chosen(views[MAR27], first_monthly)[:2] == ("SPX", date(2024, 4, 19))
        # Apr 18 is SPX Apr 19's last trading day; the PM-settled SPXW Apr 19 is still eligible
        assert chosen(views[APR18], first_monthly)[:2] == ("SPXW", date(2024, 4, 19))
        # Apr 19 at 16:15: both have expired
        assert chosen(views[APR19], first_monthly)[:2] == ("SPX", date(2024, 5, 17))
        assert chosen(views[APR19], {"selector": "nth_expiration", "n": 1})[1] == date(2024, 4, 22)

    def test_same_as_and_next_after_leg(self, views):
        a = leg("a")
        b = leg("b", option_type="put", expiration={"selector": "next_after_leg", "leg": "a"})
        result = pick(views[MAR27], a, b)
        assert [(c.root, c.expiration) for c in result.contracts.values()] == [
            ("SPX", date(2024, 5, 17)), ("SPX", date(2024, 6, 21))]
        b["expiration"]["filter"] = {"roots": ["SPXW"]}  # no SPXW after May 17
        failed = pick(views[MAR27], a, b)
        assert failed.failure.leg_id == "b" and "after leg a's SPX 2024-05-17" in failed.failure.message
        same = leg("b", option_type="put", expiration={"selector": "same_as_leg", "leg": "a"})
        assert pick(views[MAR27], a, same).contracts["b"].expiration == date(2024, 5, 17)


class TestStrikeSelectors:
    MAY17 = {"selector": "target_days", "days": 45}

    def test_delta_and_atm(self, views):
        v = views[MAR27]
        assert chosen(v, self.MAY17, {"selector": "delta", "target": 0.30})[2] == 5300
        assert chosen(v, self.MAY17, {"selector": "delta", "target": 0.30}, "put")[2] == 5100
        assert chosen(v, self.MAY17, {"selector": "atm"})[2] == 5200
        assert chosen(v, self.MAY17, {"selector": "atm"}, "put")[2] == 5200

    @pytest.mark.parametrize("option_type, tie_break, strike", [
        ("call", "further_otm", 5300), ("call", "nearer_otm", 5250),
        ("put", "further_otm", 5100), ("put", "nearer_otm", 5150)])
    def test_delta_ties(self, views, option_type, tie_break, strike):
        # 0.35 is exactly between 0.40 and 0.30 (calls 5250, 5300; puts 5150, 5100)
        target = {"selector": "delta", "target": 0.35, "tie_break": tie_break}
        assert chosen(views[MAR27], self.MAY17, target, option_type)[2] == strike

    def test_tolerance_and_nearest_any(self, views):
        strict = {"selector": "delta", "target": 0.20}
        failed = pick(views[MAR27], leg(expiration=self.MAY17, strike=strict))
        assert failed.failure.selector == "strike_selector delta"
        assert failed.failure.message == ("in SPX 2024-05-17: the nearest is 0.1 from delta 0.2, beyond the tolerance "
                                          "of 0.05")
        loose = pick(views[MAR27], leg(expiration=self.MAY17, strike=strict | {"on_no_match": "nearest_any"}))
        assert loose.ok and loose.contracts["a"].strike == 5300
        assert loose.warnings[0].message.endswith("took it anyway (on_no_match: nearest_any)")

    def test_null_deltas_are_not_eligible(self, views):
        apr12 = {"selector": "target_days", "days": 16}
        # the 5200 call's delta is null; 5150 (0.60) and 5250 (0.40) are both 0.10 from 0.50
        failed = pick(views[MAR27], leg(expiration=apr12, strike={"selector": "atm"}))
        assert "the nearest is 0.1 from delta 0.5" in failed.failure.message
        nearest = {"selector": "atm", "on_no_match": "nearest_any"}
        assert chosen(views[MAR27], apr12, nearest)[2] == 5250  # the tie goes further out of the money

    def test_forward(self, views):
        assert chosen(views[MAR27], self.MAY17, {"selector": "forward"})[2] == 5200  # forward 5212
        apr12 = {"selector": "target_days", "days": 16}
        assert chosen(views[MAR27], apr12, {"selector": "forward"})[2] == 5250  # forward 5226: 24 vs 26

    def test_a_hole_near_the_forward_skips_the_entry(self, views):
        apr26 = {"selector": "target_days", "days": 30}
        # forward 5226; 5200 and 5250 bid 0, so the nearest eligible is 5300, 74 away; usual spacing 50
        failed = pick(views[MAR27], leg(expiration=apr26, strike={"selector": "forward"}))
        assert failed.failure.message == ("in SPXW 2024-04-26: the nearest is 74 from the forward 5226, beyond the "
                                          "tolerance of 50")
        assert chosen(views[MAR27], apr26, {"selector": "forward", "tolerance_points": 100})[2] == 5300

    def test_same_strike_and_offset(self, views):
        a = leg("a", expiration=self.MAY17)
        def second(strike):
            b = leg("b", option_type="put", expiration={"selector": "same_as_leg", "leg": "a"}, strike=strike)
            result = pick(views[MAR27], a, b)
            assert result.ok, result.failure
            return result.contracts["b"].strike
        assert second({"selector": "same_strike_as", "leg": "a"}) == 5200
        assert second({"selector": "strike_offset", "leg": "a", "points": 50}) == 5250
        assert second({"selector": "strike_offset", "leg": "a", "percent": -1}) == 5150  # 5148 → 5150
        assert second({"selector": "strike_offset", "leg": "a", "points": 75}) == 5250  # 5275: tie, lower strike

    def test_usual_spacing(self):
        assert usual_spacing(np.array([5100, 5150, 5200, 5250, 5300.0]), 5226) == 50
        dense = np.array([5000, 5050, 5100, 5105, 5110, 5115, 5120, 5125, 5130, 5150, 5200.0])
        assert usual_spacing(dense, 5115) == 5
        assert usual_spacing(np.array([5000.0]), 5000) == float("inf")


class TestEligibility:
    JUN21 = {"selector": "target_days", "days": 85}

    def strikes(self, view, option_type="call", **selection):
        s = spec(leg(option_type=option_type, expiration=self.JUN21), selection=selection or None)
        rows = eligible_rows(view, s.legs[0], s)
        mask = np.array(rows.column("expiration").to_pylist()) == date(2024, 6, 21)
        return sorted(np.array(rows.column("strike").to_pylist())[mask])

    def test_quote_filters(self, views):
        v = views[MAR27]
        # 5250 bid 0 (below min_bid 0.05), 5300 crossed
        assert self.strikes(v) == [5100, 5150, 5200]
        assert self.strikes(v, min_bid=0) == [5100, 5150, 5200, 5250]
        assert self.strikes(v, min_bid=0, require_valid_quote=False) == [5100, 5150, 5200, 5250, 5300]
        assert self.strikes(v, exclude_vendor_flagged=True) == [5100, 5200]
        assert self.strikes(v, min_open_interest=100) == [5100]
        assert self.strikes(v, option_type="put") == [5100, 5150, 5200, 5250, 5300]

    def test_expired_and_roots(self, views):
        s = spec(leg(roots=["SPXW"]))
        rows = eligible_rows(views[MAR28], s.legs[0], s)
        assert set(rows.column("root").to_pylist()) == {"SPXW"}
        assert date(2024, 3, 28) not in set(rows.column("expiration").to_pylist())  # expired at 16:00

    def test_saturday_dated_monthly(self):
        # March 2008: Saturday the 22nd listed, Good Friday the 21st, so it settles Thursday the 20th
        assert is_standard_monthly(date(2008, 3, 20), CAL)
        assert not is_standard_monthly(date(2008, 3, 19), CAL)
        assert is_standard_monthly(date(2024, 4, 19), CAL) and not is_standard_monthly(date(2024, 3, 28), CAL)
        info = ExpirationInfo(root="SPX", expiration=date(2008, 3, 22), settlement_style="AM",
                              settlement_date=date(2008, 3, 20), last_trading_date=date(2008, 3, 19),
                              expiry_timestamp=datetime(2008, 3, 20, 13, 30, tzinfo=timezone.utc), days_to_expiry=1.7,
                              trading_days_to_expiry=1, contracts=1)
        assert passes_filter(info, ExpirationFilter(standard_monthly_only=True, weekdays=["SAT"]), CAL)
        assert not passes_filter(info, ExpirationFilter(weekdays=["FRI"]), CAL)
        assert not passes_filter(info, ExpirationFilter(settlement_styles=["PM"]), CAL)

    @pytest.mark.parametrize("day, eligible", [(date(2008, 3, 18), True), (date(2008, 3, 19), False)])
    def test_saturday_monthly_last_trading_day(self, day, eligible):
        as_of = datetime(day.year, day.month, day.day, 20, 15, tzinfo=timezone.utc)
        table = pa.table({"option_type": ["call"], "root": ["SPX"], "settlement_style": ["AM"],
                          "expiry_timestamp": pa.array([datetime(2008, 3, 20, 13, 30, tzinfo=timezone.utc)],
                                                       pa.timestamp("us", tz="UTC")),
                          "last_trading_date": pa.array([date(2008, 3, 19)], pa.date32()),
                          "bid": [1.0], "ask": [1.1], "open_interest": [0], "vendor_flag": [False]})
        view = MarketDataView(1, as_of, day, 1300.0, table)
        s = spec(leg())
        assert (eligible_rows(view, s.legs[0], s).num_rows == 1) is eligible


class TestStructures:
    def test_example_2_in_dependency_order(self, views):
        butterfly = StrategySpec.model_validate(example_specs()["long_butterfly_60d"])
        result = select_legs(butterfly, views[MAR27], CAL)
        assert result.ok and list(result.contracts) == ["short_call", "short_put", "long_call", "long_put"]
        # 60 days, window 50–70: SPX May 17; ATM 5200; wings at 0.25 delta: 5300 call (0.30), 5100 put (−0.30)
        assert [(c.option_type, c.strike, c.expiration) for c in result.contracts.values()] == [
            ("call", 5200, date(2024, 5, 17)), ("put", 5200, date(2024, 5, 17)), ("call", 5300, date(2024, 5, 17)),
            ("put", 5100, date(2024, 5, 17))]
        assert result.contracts["short_call"].osi_symbol == "SPX   240517C05200000"
        assert result.contracts["short_call"].row["delta"] == 0.5

    def test_selection_is_atomic(self, views):
        body = example_specs()["long_butterfly_60d"]
        body["legs"][2]["strike"] = {"selector": "delta", "target": 0.10}
        result = select_legs(StrategySpec.model_validate(body), views[MAR27], CAL)
        assert not result.ok and result.contracts == {}
        assert (result.failure.leg_id, result.failure.selector) == ("long_call", "strike_selector delta")
        assert result.failure.message == "in SPX 2024-05-17: the nearest is 0.2 from delta 0.1, beyond the tolerance of 0.05"

    def test_a_leg_roll_selects_one_leg_against_held_contracts(self, views):
        butterfly = StrategySpec.model_validate(example_specs()["long_butterfly_60d"])
        held = select_legs(butterfly, views[MAR27], CAL).contracts
        rolled = select_legs(butterfly, views[MAR27], CAL, legs=["short_put"], fixed={"short_call": held["short_call"]})
        assert list(rolled.contracts) == ["short_put"] and rolled.contracts["short_put"].strike == 5200
