"""Golden tests of the book (TEST-1, book part): fills, sizing, hedging, marking and accounting.

Each test builds small views by hand and drives the book step by step, as the step loop will
(plan Phase 13). Every expected number is worked out in the comment beside it: m = 100, prices in
index points, money in dollars, positive cash flow is cash received. The accounting invariants
(ENG-33) are checked on every run.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pyarrow as pa
import pytest

from prophetovol.data.ivolatility import osi_symbol
from prophetovol.engine.book import Book, BookSettings
from prophetovol.engine.fills import fill_model
from prophetovol.engine.hedging import Band, NoHedge
from prophetovol.engine.invariants import InvariantViolation, check_invariants
from prophetovol.engine.orders import OpenLeg
from prophetovol.engine.sizing import Contracts, Notional, round_units
from prophetovol.engine.view import ENGINE_COLUMNS, MarketDataView
from prophetovol.registry.params.fills import CrossSpreadParams, MidParams, MidPlusFractionParams
from prophetovol.registry.params.hedge import BandParams, NoHedgeParams
from prophetovol.registry.params.sizing import ContractsParams, NotionalParams
from prophetovol.results.recorder import RunRecorder
from prophetovol.results.records import RECORD_MODELS

EXPIRY = date(2024, 5, 17)
DAY0 = date(2024, 4, 1)
MID = fill_model(MidParams(fill_model="mid"))
CROSS = fill_model(CrossSpreadParams(fill_model="cross_spread"))
NO_HEDGE = NoHedge(NoHedgeParams(rule="none"))


def contract(strike, call=True, bid=9.9, ask=10.1, delta=0.5, gamma=0.0, vega=0.0, theta=0.0):
    return {"osi_symbol": osi_symbol("SPX", EXPIRY, "call" if call else "put", strike), "root": "SPX",
            "vendor_symbol": "SPX", "vendor_root": "SPX", "settlement_style": "AM", "expiration": EXPIRY,
            "settlement_date": EXPIRY, "last_trading_date": EXPIRY - timedelta(days=1),
            "expiry_timestamp": datetime(2024, 5, 17, 13, 30, tzinfo=timezone.utc), "strike": float(strike),
            "option_type": "call" if call else "put", "bid": bid, "ask": ask, "delta": delta, "gamma": gamma,
            "vega": vega, "theta": theta, "iv": 0.15, "forward": 5000.0, "forward_source": "vendor",
            "time_to_expiry_years": 0.1, "days_to_expiry": 36.5, "trading_days_to_expiry": 25,
            "open_interest": 0, "vendor_flag": False}


def view(step, index, *contracts):
    day = DAY0 + timedelta(days=step - 1)
    as_of = datetime(day.year, day.month, day.day, 20, 15, tzinfo=timezone.utc)
    rows = [{k: c.get(k) for k in ENGINE_COLUMNS} | {"as_of": as_of, "as_of_date": day} for c in contracts]
    table = pa.Table.from_pylist(rows) if rows else pa.table({"osi_symbol": pa.array([], pa.string())})
    return MarketDataView(step, as_of, day, index, table)


def book(fill=MID, commission=0.0, hedge_bps=0.0, warn=5, capital=1_000_000.0):
    return Book(BookSettings(multiplier=100, capital=capital, fill=fill, commission_per_contract=commission,
                             hedge_cost_bps=hedge_bps, stale_mark_warning_steps=warn), RunRecorder("run_test"))


def step(b, v, actions=None, rule=NO_HEDGE, settle=None):
    """One step in ENG-1's order: settle, mark, orders, hedge, record."""
    b.begin_step(v)
    if settle:
        settle(b)
    b.mark()
    b.retry_pending_closes()
    if actions:
        actions(b)
    b.rebalance_hedges(rule)
    b.end_step()


def positions(b, step_no=None, leg=None):
    return [r for r in b.recorder.rows("position_snapshots")
            if (step_no is None or r["step"] == step_no) and (leg is None or r["leg_id"] == leg)]


def portfolio(b):
    return b.recorder.rows("portfolio_snapshots")


class TestFirstStepCost:
    """A 10-lot bought at 9.90/10.10 (mid 10.00), commission $0.65 per contract: the first step shows the cost."""

    @pytest.mark.parametrize("fill, price, cash, pnl", [
        (CROSS, 10.10, -10_106.50, -106.50),   # −10 × 10.10 × 100 − 6.50; P&L = 10,000 − 10,106.50
        (MID, 10.00, -10_006.50, -6.50),       # only the commission
        (fill_model(MidPlusFractionParams(fill_model="mid_plus_fraction", fraction=0.5)), 10.05, -10_056.50, -56.50),
    ])
    def test_buy(self, fill, price, cash, pnl):
        b = book(fill, commission=0.65)
        c = contract(5000)
        step(b, view(1, 5000, c), lambda b: b.open_structure([OpenLeg("call", c, 10)], units=10))
        trade = b.recorder.rows("trades")[0]
        assert (trade["price"], trade["fees"], trade["cash_flow"]) == pytest.approx((price, 6.50, cash))
        row = positions(b, 1)[0]
        assert row["market_value"] == pytest.approx(10_000) and row["mark"] == 10.0 and row["mark_source"] == "mid"
        assert (row["cash_flow"], row["fees"], row["period_pnl"]) == pytest.approx((cash, 6.50, pnl))
        assert portfolio(b)[0]["period_pnl"] == pytest.approx(pnl)
        assert portfolio(b)[0]["equity"] == pytest.approx(1_000_000 + pnl)
        check_invariants(b.recorder)

    def test_sell_crossing_the_spread(self):
        b = book(CROSS, commission=0.65)
        c = contract(5000)
        step(b, view(1, 5000, c), lambda b: b.open_structure([OpenLeg("call", c, -10)], units=10))
        row = positions(b, 1)[0]
        # sold at the bid: +10 × 9.90 × 100 − 6.50 = 9,893.50; market value −10,000; P&L −106.50
        assert (row["cash_flow"], row["market_value"], row["period_pnl"]) == pytest.approx((9_893.50, -10_000, -106.50))


class TestSizing:
    def test_contracts_and_notional(self):
        assert Contracts(ContractsParams(method="contracts", quantity=10)).units(5000, 100) == 10
        notional = Notional(NotionalParams(method="notional", notional=1_250_000))
        assert notional.units(5000, 100) == 2.5  # 1,250,000 / (5000 × 100)

    @pytest.mark.parametrize("units, rounding, expected", [
        (2.0, "whole", 2.0), (2.5, "whole", 2.0), (2.5, "fractional", 2.5),
        (0.8, "whole", None),  # below one unit: the entry is skipped
        (0.8, "fractional", 0.8), (2.9999999999, "whole", 3.0)])
    def test_rounding(self, units, rounding, expected):
        assert round_units(units, rounding) == expected


class TestHedgeBand:
    """Example 3: short 10 puts (−0.25), long 10 puts (−0.20), band 0 to 0.08, target 0.03, N = 10, index 5000."""

    def test_no_trade_inside_and_reset_to_target_outside(self):
        b = book(hedge_bps=2.0)
        rule = Band(BandParams(rule="band", lower=0.0, upper=0.08, target=0.03))
        deltas = [(-0.25, -0.20), (-0.35, -0.25), (-0.30, -0.25), (-0.32, -0.25)]

        def legs(i):
            return contract(4800, call=False, delta=deltas[i][0]), contract(4700, call=False, delta=deltas[i][1])

        short, long = legs(0)
        step(b, view(1, 5000, short, long), lambda b: b.open_structure(
            [OpenLeg("short_put", short, -10), OpenLeg("long_put", long, 10)], units=10), rule)
        for i in (1, 2, 3):
            step(b, view(i + 1, 5000, *legs(i)), rule=rule)
        hedges = [t for t in b.recorder.rows("trades") if t["leg_id"] == "hedge"]
        # step 1: Σqδ = 2.5 − 2.0 = 0.5, measure 0.05: inside, no trade
        # step 2: Σqδ = 3.5 − 2.5 = 1.0, measure 0.10 > 0.08: h = 100 × (0.03 × 10 − 1.0) = −70
        # step 3: Σqδ = 3.0 − 2.5 = 0.5, measure (0.5 − 0.7) / 10 = −0.02 < 0: h = 100 × (0.3 − 0.5) = −20, so +50
        # step 4: Σqδ = 3.2 − 2.5 = 0.7, measure (0.7 − 0.2) / 10 = 0.05: inside
        assert [(t["step"], t["quantity"]) for t in hedges] == [(2, pytest.approx(-70)), (3, pytest.approx(50))]
        # hedge cost 2 bps of notional: 0.0002 × 70 × 5000 = 70 and 0.0002 × 50 × 5000 = 50
        assert [t["fees"] for t in hedges] == pytest.approx([70, 50])
        assert [r["quantity"] for r in positions(b, leg="hedge")] == pytest.approx([-70, -20, -20])
        # the index did not move, so the hedge's P&L is its cost
        assert [r["period_pnl"] for r in positions(b, leg="hedge")] == pytest.approx([-70, -50, 0])
        check_invariants(b.recorder)


class TestFullHedge:
    """Example 1: short 10 calls, hedged to flat at every step (band 0, 0, 0); mid fills and no costs."""

    def test_three_steps(self):
        b = book()
        rule = Band(BandParams(rule="band", lower=0.0, upper=0.0, target=0.0))
        path = [(5000, 50.0, 0.30), (5010, 54.0, 0.35), (4990, 45.0, 0.30)]  # index, call mid, call delta
        calls = [contract(5000, bid=m - 0.5, ask=m + 0.5, delta=d, gamma=0.001, vega=8.0, theta=-1.5)
                 for _, m, d in path]
        step(b, view(1, 5000, calls[0]), lambda b: b.open_structure([OpenLeg("short_call", calls[0], -10)], 10), rule)
        step(b, view(2, 5010, calls[1]), rule=rule)
        step(b, view(3, 4990, calls[2]), rule=rule)
        # hedge h = 100 × (0 − Σqδ): Σqδ = −3.0, −3.5, −3.0 → h = 300, 350, 300
        assert [r["quantity"] for r in positions(b, leg="hedge")] == pytest.approx([300, 350, 300])
        # option: MV −50,000, −54,000, −45,000 → period P&L 0 (sold at mid), −4,000, +9,000
        assert [r["period_pnl"] for r in positions(b, leg="short_call")] == pytest.approx([0, -4_000, 9_000])
        # hedge: 300 × 10 = +3,000 at step 2 (then +50 at 5010); 350 × −20 = −7,000 at step 3
        assert [r["period_pnl"] for r in positions(b, leg="hedge")] == pytest.approx([0, 3_000, -7_000])
        assert [p["period_pnl"] for p in portfolio(b)] == pytest.approx([0, -1_000, 2_000])
        assert [p["cumulative_pnl"] for p in portfolio(b)] == pytest.approx([0, -1_000, 1_000])
        # cash: +50,000 − 1,500,000 − 250,500 + 249,500 = −1,451,000; final MV −45,000 + 1,497,000 = 1,452,000
        assert sum(p["cash_flow"] for p in portfolio(b)) == pytest.approx(-1_451_000)
        assert portfolio(b)[-1]["market_value"] == pytest.approx(1_452_000)
        # fully hedged: the portfolio's dollar delta is zero at every step
        assert [p["dollar_delta"] for p in portfolio(b)] == pytest.approx([0, 0, 0], abs=1e-6)
        check_invariants(b.recorder)

    def test_dollar_greeks(self):
        b = book()
        c = contract(5000, bid=49.5, ask=50.5, delta=0.30, gamma=0.001, vega=8.0, theta=-1.5)
        rule = Band(BandParams(rule="band", lower=0.0, upper=0.0, target=0.0))
        step(b, view(1, 5000, c), lambda b: b.open_structure([OpenLeg("short_call", c, -10)], 10), rule)
        option, hedge = positions(b, 1)
        # q = −10, m = 100, S = 5000
        assert option["dollar_delta"] == pytest.approx(-1_500_000)  # 0.30 × −10 × 100 × 5000
        assert option["dollar_gamma_1pct"] == pytest.approx(-250_000)  # 0.001 × −10 × 100 × 5000² × 0.01
        assert option["dollar_vega"] == pytest.approx(-8_000)  # 8 × −10 × 100
        assert option["dollar_theta"] == pytest.approx(1_500)  # −1.5 × −10 × 100
        assert hedge["dollar_delta"] == pytest.approx(1_500_000) and hedge["mark_source"] == "index"  # 300 × 5000
        assert (hedge["dollar_gamma_1pct"], hedge["dollar_vega"], hedge["dollar_theta"]) == (0.0, 0.0, 0.0)


class TestMarks:
    def test_stale_mark_carried_with_a_warning_after_n_steps(self):
        b = book(warn=2)
        good = contract(5000)  # mid 10
        step(b, view(1, 5000, good), lambda b: b.open_structure([OpenLeg("call", good, 1)], 1))
        step(b, view(2, 5000))  # absent from the snapshot
        step(b, view(3, 5000, contract(5000, bid=12.0, ask=11.0)))  # crossed
        step(b, view(4, 5000))
        step(b, view(5, 5000, contract(5000, bid=11.9, ask=12.1)))  # valid again: mid 12
        rows = positions(b)
        assert [r["mark"] for r in rows] == [10, 10, 10, 10, 12]
        assert [r["mark_source"] for r in rows] == ["mid", "stale", "stale", "stale", "mid"]
        assert [("stale_mark" in r["flags"]) for r in rows] == [False, True, True, True, False]
        # (12 − 10) × 1 × 100 = 200 once the quote is valid again
        assert [r["period_pnl"] for r in rows] == pytest.approx([0, 0, 0, 0, 200])
        stale = [e for e in b.recorder.rows("events") if e["type"] == "stale_mark"]
        assert [(e["step"], e["level"]) for e in stale] == [(2, "info"), (3, "info"), (4, "warning")]
        assert "missing from the snapshot" in stale[0]["message"] and "invalid quote (12.0/11.0)" in stale[1]["message"]
        check_invariants(b.recorder)

    def test_closing_order_retried_until_filled(self):
        b = book(CROSS)
        c = contract(5000)
        step(b, view(1, 5000, c), lambda b: b.open_structure([OpenLeg("call", c, 1)], 1))  # bought 10.10
        step(b, view(2, 5000, contract(5000, bid=0.0, ask=0.0)), lambda b: b.close_leg("S1", "call", "stop"))
        assert positions(b, 2)[0]["quantity"] == 1 and positions(b, 2)[0]["mark_source"] == "stale"
        assert b.recorder.rows("structures")[0]["status"] == "closing"
        step(b, view(3, 5000, contract(5000, bid=11.9, ask=12.1)))  # retried: sold at the bid, 11.90
        row = positions(b, 3)[0]
        # cash +1 × 11.90 × 100 = 1,190; market value 0; P&L 0 − 1,000 (mark 10 at step 2) + 1,190 = 190
        assert (row["quantity"], row["cash_flow"], row["period_pnl"]) == pytest.approx((0, 1_190, 190))
        assert row["mark"] == 11.9 and row["mark_source"] == "fill"
        types = [e["type"] for e in b.recorder.rows("events")]
        assert types == ["stale_mark", "order_not_filled", "close"]  # step 2 is also marked stale
        assert b.recorder.rows("structures")[0]["status"] == "closed"
        assert b.recorder.rows("structures")[0]["closed_step"] == 3
        check_invariants(b.recorder)

    def test_forced_close_without_a_quote_uses_the_last_valid_mark(self):
        b = book(CROSS, commission=0.65)
        c = contract(5000)
        step(b, view(1, 5000, c), lambda b: b.open_structure([OpenLeg("call", c, 1)], 1))
        step(b, view(2, 5000), lambda b: b.close_leg("S1", "call", "forced_close_am", forced=True))
        row = positions(b, 2)[0]
        # at the last valid mark 10, no fill cost, commission paid: +1 × 10 × 100 − 0.65 = 999.35
        assert (row["cash_flow"], row["fees"], row["period_pnl"]) == pytest.approx((999.35, 0.65, -0.65))
        assert "forced_close_stale" in row["flags"] and b.pending_closes == {}
        assert b.recorder.rows("trades")[-1]["forced"] is True
        check_invariants(b.recorder)


class TestSettlementAndStructures:
    def test_pm_settlement_is_a_cash_flow(self):
        b = book()
        c = contract(5000, bid=29.5, ask=30.5)
        step(b, view(1, 5000, c), lambda b: b.open_structure([OpenLeg("call", c, 10)], 10))
        step(b, view(2, 5050), settle=lambda b: b.settle("S1", "call", 50.0))
        row = positions(b, 2)[0]
        # 10 × 50 × 100 = 50,000 received; P&L 0 − 30,000 + 50,000 = 20,000
        assert (row["cash_flow"], row["market_value"], row["period_pnl"]) == pytest.approx((50_000, 0, 20_000))
        assert row["mark_source"] == "settlement" and not b.open_structures()
        assert [e["type"] for e in b.recorder.rows("events")] == ["settlement"]
        check_invariants(b.recorder)

    def test_opening_is_all_legs_or_none(self):
        b = book()
        good, bad = contract(5000), contract(5100, bid=0.0, ask=0.0)
        step(b, view(1, 5000, good, bad), lambda b: b.open_structure(
            [OpenLeg("a", good, 1), OpenLeg("b", bad, -1)], 1))
        assert b.structures == [] and b.recorder.rows("trades") == []
        assert b.recorder.rows("events")[0]["message"].endswith(f"b ({bad['osi_symbol']})")
        assert portfolio(b)[0]["open_structures"] == 0

    def test_hedge_closes_with_the_last_leg(self):
        b = book()
        rule = Band(BandParams(rule="band", lower=0.0, upper=0.0, target=0.0))
        c = contract(5000, delta=0.30)
        step(b, view(1, 5000, c), lambda b: b.open_structure([OpenLeg("short_call", c, -10)], 10), rule)
        step(b, view(2, 5000, c), lambda b: b.close_leg("S1", "short_call", "close"), rule)
        assert [t["quantity"] for t in b.recorder.rows("trades") if t["leg_id"] == "hedge"] == pytest.approx([300, -300])
        assert b.recorder.rows("structures")[0]["status"] == "closed" and not b.open_structures()
        check_invariants(b.recorder)

    def test_structure_ids_and_parent(self):
        b = book()
        c = contract(5000)
        step(b, view(1, 5000, c), lambda b: b.open_structure([OpenLeg("a", c, 1)], 1))
        step(b, view(2, 5000, c), lambda b: (b.close_leg("S1", "a", "roll"),
                                             b.open_structure([OpenLeg("a", c, 1)], 1, "roll", parent_id="S1")))
        structures = b.recorder.rows("structures")
        assert [(s["structure_id"], s["parent_id"], s["status"]) for s in structures] == [
            ("S1", None, "closed"), ("S2", "S1", "open")]


class TestRecordsAndInvariants:
    def run(self):
        b = book(CROSS, commission=1.0)
        c = contract(5000, delta=0.3)
        step(b, view(1, 5000, c), lambda b: b.open_structure([OpenLeg("a", c, -2)], 2),
             Band(BandParams(rule="band", lower=0.0, upper=0.0, target=0.0)))
        step(b, view(2, 5020, contract(5000, bid=11.0, ask=11.4, delta=0.35)),
             rule=Band(BandParams(rule="band", lower=0.0, upper=0.0, target=0.0)))
        return b

    def test_tables_match_the_record_models(self):
        tables = self.run().recorder.tables()
        assert set(tables) == set(RECORD_MODELS)
        for name, model in RECORD_MODELS.items():
            assert tables[name].column_names == list(model.model_fields)
            for row in tables[name].to_pylist():
                model.model_validate(row | ({"details": {}} if name == "events" else {}))

    def test_violations_name_the_step_and_security(self):
        b = self.run()
        check_invariants(b.recorder)
        b.recorder.rows("portfolio_snapshots")[1]["market_value"] += 1.0
        with pytest.raises(InvariantViolation, match="step 2: portfolio market_value"):
            check_invariants(b.recorder)
        b.recorder.rows("portfolio_snapshots")[1]["market_value"] -= 1.0
        b.recorder.rows("position_snapshots")[0]["cumulative_pnl"] += 0.01
        with pytest.raises(InvariantViolation, match="step 1, S1/a/SPX   240517C05000000: cumulative P&L"):
            check_invariants(b.recorder)
