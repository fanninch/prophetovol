"""Golden tests of the rules and the step loop (TEST-1, rules part).

Runs go through :func:`run_engine` on small hand-built views in Eastern Daylight Time: snapshots at
16:15 ET (20:15 UTC), PM expiries at 16:00 ET, AM expiries at 09:30 ET. Fills are at the mid with no
costs unless a test says otherwise, so every number is worked out in the comments (m = 100). The
accounting invariants are checked at the end of every run (ENG-33).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pyarrow as pa
import pytest

from prophetovol.core.context import CallContext
from prophetovol.data.ivolatility import osi_symbol
from prophetovol.engine.book import BookSettings
from prophetovol.engine.constructor import _conditions
from prophetovol.engine.fills import fill_model
from prophetovol.engine.loop import EngineSettings, run_engine
from prophetovol.engine.schedule import Step, StepSchedule
from prophetovol.engine.view import ENGINE_COLUMNS, MarketDataView
from prophetovol.reference.calendar import nyse_calendar
from prophetovol.registry.params.fills import MidParams
from prophetovol.results.recorder import RunRecorder
from prophetovol.runs.service import BacktestService
from prophetovol.strategy.model import StrategySpec
from prophetovol.testdata.golden import pm_call_to_expiry, write_rows

CAL = nyse_calendar()
CTX = CallContext.for_channel("library")
UTC = timezone.utc


def as_of(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 20, 15, tzinfo=UTC)


def contract(day, expiration, strike, mid, delta, call=True, style="PM", valid=True, root=None):
    expiry = datetime(expiration.year, expiration.month, expiration.day, 20 if style == "PM" else 13,
                      0 if style == "PM" else 30, tzinfo=UTC)
    bid, ask = (mid - 0.05, mid + 0.05) if valid else (0.0, 0.0)
    root = root or ("SPXW" if style == "PM" else "SPX")
    return {"osi_symbol": osi_symbol(root, expiration, "call" if call else "put", strike), "root": root,
            "vendor_symbol": root, "vendor_root": root, "settlement_style": style, "expiration": expiration,
            "settlement_date": expiration,
            "last_trading_date": expiration if style == "PM" else CAL.previous_session(expiration),
            "expiry_timestamp": expiry, "time_to_expiry_years": None,
            "days_to_expiry": (expiry - as_of(day)).total_seconds() / 86_400,
            "trading_days_to_expiry": CAL.sessions_after_through(day, expiration), "strike": float(strike),
            "option_type": "call" if call else "put", "bid": bid, "ask": ask, "iv": 0.15, "forward": 5000.0,
            "forward_source": "vendor", "delta": delta, "gamma": 0.0, "vega": 0.0, "theta": 0.0,
            "open_interest": 0, "vendor_flag": False}


def run(spec_body, days, chains, index=None, missing=(), settings=None, **kwargs):
    """Run a spec over hand-built steps. ``chains[i]`` is the list of contracts on ``days[i]``."""
    spec = StrategySpec.model_validate(spec_body)
    steps = [Step(seq=i + 1, day=d, as_of=as_of(d)) for i, d in enumerate(days)]
    views = []
    for i, (d, rows) in enumerate(zip(days, chains)):
        table = pa.Table.from_pylist([{k: r.get(k) for k in ENGINE_COLUMNS} | {"as_of": as_of(d), "as_of_date": d}
                                      for r in rows]) if rows else pa.table({"osi_symbol": pa.array([], pa.string())})
        views.append(MarketDataView(i + 1, as_of(d), d, (index or [5000.0] * len(days))[i], table))
    recorder = RunRecorder("run_test")
    settings = settings or EngineSettings(BookSettings(multiplier=100, capital=1_000_000,
                                                       fill=fill_model(MidParams(fill_model="mid"))))
    outcome = run_engine(spec, settings, StepSchedule(steps=steps, missing_days=list(missing)), views, CAL, recorder,
                         **kwargs)
    return outcome, recorder


def body(legs, triggers=(), entry=None, expiry_handling="close_structure", quantity=1, sizing=None):
    return {"id": "golden", "underlying": "SPX", "legs": legs, "triggers": list(triggers),
            "entry": entry or {"schedule": "once"}, "expiry_handling": expiry_handling,
            "sizing": sizing or {"method": "contracts", "quantity": quantity}}


def leg(leg_id, side="long", expiration=None, strike=None, option_type="call", **extra):
    return {"id": leg_id, "option_type": option_type, "side": side,
            "expiration": expiration or {"selector": "target_days", "days": 3, "max_days": 30},
            "strike": strike or {"selector": "atm"}, **extra}


def rows(recorder, table, **match):
    return [r for r in recorder.rows(table) if all(r[k] == v for k, v in match.items())]


def events(recorder, *types):
    return [(e["step"], e["type"]) for e in recorder.rows("events") if not types or e["type"] in types]


def pnl(recorder):
    return [p["period_pnl"] for p in recorder.rows("portfolio_snapshots")]


MAY14, MAY15, MAY16, MAY17 = date(2024, 5, 14), date(2024, 5, 15), date(2024, 5, 16), date(2024, 5, 17)
JUN3, JUN4, JUN5, JUN6, JUN7 = (date(2024, 6, d) for d in (3, 4, 5, 6, 7))
JUN12, JUN13, JUN14, JUN21 = date(2024, 6, 12), date(2024, 6, 13), date(2024, 6, 14), date(2024, 6, 21)


class TestSettlementThroughTheWholePath:
    def test_long_pm_call_held_to_expiry_and_settled(self, tmp_path):
        """The Phase 5 chain through ingest, pre-flight and the provider: Wed Jun 12 to Fri Jun 14, 2024."""
        path = write_rows(pm_call_to_expiry().rows, tmp_path / "chain.csv")
        spec = body([leg("call", expiration={"selector": "target_days", "days": 2}, roots=["SPXW"],
                         hold_to_expiration=True, strike={"selector": "delta", "target": 0.55})])
        with BacktestService.open(tmp_path / "home") as svc:
            job = svc.import_files([path], CTX)
            svc.commit_import(job.result["import_id"], "replace", CTX)
            svc.publish_spec(spec, CTX)
            report = svc.preflight_run("golden", {"start_date": JUN12, "end_date": JUN14, "capital": 1_000_000,
                                                  "fill_model": "mid"}, CTX)
            provider = svc.market_data(report, svc.get_spec("golden"))
            recorder = RunRecorder("run")
            settings = EngineSettings(BookSettings(multiplier=100, capital=1_000_000,
                                                   fill=fill_model(report.config.fill_model_params())))
            outcome = run_engine(svc.get_spec("golden"), settings, report.schedule, provider.views(), CAL, recorder)
        assert outcome.status == "completed" and outcome.steps_completed == 3
        call = rows(recorder, "position_snapshots", leg_id="call")
        # bought the 5000 call at the mid 30.50; Thursday's mid 35.50: +500; Friday it settles at 5050 − 5000 = 50:
        # 1 contract × 50 × 100 = 5,000 received, P&L 5,000 − 3,550 = 1,450
        assert [r["mark"] for r in call] == [30.5, 35.5, 50.0]
        assert [r["mark_source"] for r in call] == ["mid", "mid", "settlement"]
        assert pnl(recorder) == pytest.approx([0, 500, 1_450])
        assert recorder.rows("portfolio_snapshots")[-1]["cumulative_pnl"] == pytest.approx(1_950)  # (50 − 30.5) × 100
        assert events(recorder, "entry", "settlement") == [(1, "entry"), (3, "settlement")]
        assert recorder.rows("structures")[0]["status"] == "closed"


class TestForcedCloses:
    SPEC = body([leg("short_call", side="short", expiration={"selector": "target_days", "days": 3, "max_days": 5},
                     strike={"selector": "delta", "target": 0.30})])

    def chains(self, valid_last=True):
        exp = MAY17  # SPX AM monthly: settles Fri 09:30, last trading day Thu May 16
        return [[contract(MAY14, exp, 5000, 10, 0.30, style="AM")], [contract(MAY15, exp, 5000, 12, 0.35, style="AM")],
                [contract(MAY16, exp, 5000, 14, 0.40, style="AM", valid=valid_last)]]

    def test_am_leg_closed_on_its_last_trading_day(self):
        outcome, rec = run(self.SPEC, [MAY14, MAY15, MAY16], self.chains())
        # sold at 10; marked 12 (−200); bought back at 14 on Thursday (−200)
        assert pnl(rec) == pytest.approx([0, -200, -200])
        trade = rec.rows("trades")[-1]
        assert (trade["reason"], trade["forced"], trade["price"]) == ("forced_close_am", True, 14.0)
        assert events(rec, "forced_close_am") == [(3, "forced_close_am")]
        assert rec.rows("structures")[0]["status"] == "closed"

    def test_without_a_valid_quote_at_the_last_valid_mark(self):
        outcome, rec = run(self.SPEC, [MAY14, MAY15, MAY16], self.chains(valid_last=False))
        last = rows(rec, "position_snapshots", step=3)[0]
        # closed at Wednesday's mark 12: cash −1,200, P&L 0 − (−1,200) − 1,200 = 0
        assert last["mark"] == 12.0 and "forced_close_stale" in last["flags"]
        assert pnl(rec) == pytest.approx([0, -200, 0])

    def test_pm_leg_closed_before_a_skipped_settlement_date(self):
        spec = body([leg("call", expiration={"selector": "target_days", "days": 2})])
        chains = [[contract(JUN12, JUN14, 5000, 30, 0.5)], [contract(JUN13, JUN14, 5000, 35, 0.6)]]
        outcome, rec = run(spec, [JUN12, JUN13], chains, missing=[JUN14])
        trade = rec.rows("trades")[-1]
        assert (trade["step"], trade["reason"], trade["forced"], trade["price"]) == (
            2, "forced_close_missing_expiry", True, 35.0)
        assert pnl(rec) == pytest.approx([0, 500])


class TestTriggers:
    """A 2-lot short call (delta 0.30) on SPXW Jun 21, Mon Jun 3 to Wed Jun 5, 2024."""

    def chains(self, a_mid_2=14.0, b_mid_3=0.5):
        a = lambda d, m, de: contract(d, JUN21, 5000, m, de)
        b = lambda d, m, de: contract(d, JUN21, 5100, m, de)
        return [[a(JUN3, 10, 0.30), b(JUN3, 5, 0.20)],
                [a(JUN4, a_mid_2, 0.55), b(JUN4, 6, 0.30)],
                [a(JUN5, 16, 0.70), b(JUN5, b_mid_3, 0.10)]]

    ROLL = {"name": "roll_on_delta", "scope": {"leg": "short_call"}, "action": "roll",
            "any_of": [{"condition": "leg_abs_delta_above", "leg": "short_call", "threshold": 0.5}]}

    def spec(self, *triggers):
        return body([leg("short_call", side="short", expiration={"selector": "target_days", "days": 18},
                         strike={"selector": "delta", "target": 0.30})], triggers=triggers, quantity=2)

    def test_leg_roll_on_delta_then_profit_target_across_the_roll(self):
        target = {"name": "take_profit", "scope": "structure", "action": "close",
                  "any_of": [{"condition": "structure_pnl_per_unit_at_or_above", "amount": 150}]}
        outcome, rec = run(self.spec(self.ROLL, target), [JUN3, JUN4, JUN5], self.chains())
        # step 2: A's delta 0.55 > 0.50, so the leg rolls: A bought back at 14 (2 × −400 = −800), B sold at 6
        # step 3: B at 0.50: +1,100 (2 × 5.50 × 100); the structure has made −800 + 1,100 = 300, 150 per unit
        assert pnl(rec) == pytest.approx([0, -800, 1_100])
        legs = rows(rec, "position_snapshots", leg_id="short_call")
        assert [(r["step"], r["strike"], r["quantity"]) for r in legs] == [
            (1, 5000, -2), (2, 5000, 0), (2, 5100, -2), (3, 5100, 0)]
        assert {r["structure_id"] for r in legs} == {"S1"}  # a leg roll keeps the structure
        assert events(rec, "trigger_fired", "roll", "close") == [
            (2, "trigger_fired"), (2, "close"), (2, "roll"), (3, "trigger_fired"), (3, "close")]
        assert rec.rows("structures")[0]["cumulative_pnl"] == pytest.approx(300)
        # each trigger event names the condition that fired and its measured value
        assert [e["message"] for e in rec.rows("events") if e["type"] == "trigger_fired"] == [
            "roll_on_delta (leg_abs_delta_above 0.55): roll short_call",
            "take_profit (structure_pnl_per_unit_at_or_above 150): close structure"]

    def test_trigger_message_values(self):
        # dollars of 1,000 or more with cents, other values to four significant digits, no value without one
        conditions = ({"condition": "structure_pnl_per_unit_at_or_above", "value": 1250.0},
                      {"condition": "leg_abs_delta_below", "value": 0.135714},
                      {"condition": "structure_pnl_per_unit_at_or_below", "value": -2500.456},
                      {"condition": "leg_days_to_expiry_at_or_below", "value": 14.989583},
                      {"condition": "trading_days_held_at_least", "value": None})
        assert _conditions(conditions) == (
            "structure_pnl_per_unit_at_or_above 1,250.00, leg_abs_delta_below 0.1357, "
            "structure_pnl_per_unit_at_or_below -2,500.46, leg_days_to_expiry_at_or_below 14.99, "
            "trading_days_held_at_least")

    def test_stop_wins_over_a_leg_roll_and_both_are_recorded(self):
        stop = {"name": "stop", "scope": "structure", "action": "close",
                "any_of": [{"condition": "structure_pnl_per_unit_at_or_below", "amount": -300}]}
        outcome, rec = run(self.spec(self.ROLL, stop), [JUN3, JUN4, JUN5], self.chains())
        fired = [e for e in rec.rows("events") if e["type"] == "trigger_fired"][0]
        # step 2: −800 over 2 units is −400 ≤ −300; structure close outranks the leg roll (SPEC-44)
        assert fired["details"]["chosen"] == "stop"
        assert [f["trigger"] for f in fired["details"]["fired"]] == ["roll_on_delta", "stop"]
        assert pnl(rec) == pytest.approx([0, -800, 0]) and not rows(rec, "position_snapshots", step=3)

    def test_a_leg_roll_does_not_make_room_for_an_entry(self):
        spec = self.spec(self.ROLL)
        spec["entry"] = {"schedule": "when_flat"}
        outcome, rec = run(spec, [JUN3, JUN4, JUN5], self.chains())
        # step 2's leg roll briefly leaves S1 without its leg; it still counts as open, so no second structure
        assert [s["structure_id"] for s in rec.rows("structures")] == ["S1"]
        assert events(rec, "entry") == [(1, "entry")]

    def test_null_delta_is_false_with_an_event(self):
        chains = self.chains()
        chains[1][0]["delta"] = None
        outcome, rec = run(self.spec(self.ROLL), [JUN3, JUN4, JUN5], chains)
        assert events(rec, "condition_null_greek", "trigger_fired") == [(2, "condition_null_greek"), (3, "trigger_fired")]

    def test_roll_waits_for_its_close_to_fill(self):
        chains = self.chains()
        chains[1][0]["bid"] = chains[1][0]["ask"] = 0.0  # A cannot be bought back on Tuesday
        chains[2][1]["delta"] = 0.30  # B is the 0.30-delta call again on Wednesday
        outcome, rec = run(self.spec(self.ROLL), [JUN3, JUN4, JUN5], chains)
        trades = [(t["step"], t["action"], t["osi_symbol"][-8:-3]) for t in rec.rows("trades")]
        # Tuesday: the close waits and B is not sold; Wednesday: A is bought back, then B is sold
        assert trades == [(1, "open", "05000"), (3, "close", "05000"), (3, "open", "05100")]
        assert (2, "order_not_filled") in events(rec)


class TestStructureRolls:
    """A long ATM call on SPXW Jun 7 rolled into Jun 14, Mon Jun 3 to Thu Jun 6, 2024."""

    def chains(self):
        return [[contract(d, JUN7, 5000, 20 - i, 0.5), contract(d, JUN14, 5000, 30 - i, 0.5)]
                for i, d in enumerate([JUN3, JUN4, JUN5, JUN6])]

    @pytest.mark.parametrize("condition, roll_step, value", [
        ({"condition": "structure_min_days_to_expiry_at_or_below", "days": 2, "unit": "calendar_days"}, 3, "1.99"),
        ({"condition": "structure_min_days_to_expiry_at_or_below", "days": 3, "unit": "trading_days"}, 2, "3"),
        ({"condition": "leg_days_to_expiry_at_or_below", "leg": "call", "days": 3, "unit": "trading_days"}, 2, "3"),
    ])
    def test_roll_on_time_to_expiry(self, condition, roll_step, value):
        spec = body([leg("call", expiration={"selector": "target_days", "days": 7})],
                    triggers=[{"name": "roll_near_expiry", "scope": "structure", "action": "roll",
                               "any_of": [condition]}])
        outcome, rec = run(spec, [JUN3, JUN4, JUN5, JUN6], self.chains())
        structures = rec.rows("structures")
        # Jun 3: Jun 7 is 3.99 days out (7 − 3.99 = 3.01), Jun 14 10.99 (3.99): Jun 7. At the roll, Jun 14 is nearer 7
        assert [(s["structure_id"], s["parent_id"], s["status"]) for s in structures] == [
            ("S1", None, "closed"), ("S2", "S1", "open")]
        assert structures[0]["closed_step"] == roll_step and structures[1]["opened_step"] == roll_step
        opened = rows(rec, "position_snapshots", structure_id="S2")[0]
        assert opened["expiration"] == JUN14
        assert (roll_step, "roll") in events(rec, "roll")
        # Wed Jun 5 16:15 to Fri Jun 7 16:00 is 1.99 calendar days; from Tue Jun 4, Jun 5, 6 and 7 are 3 trading days
        fired = [e["message"] for e in rec.rows("events") if e["type"] == "trigger_fired"]
        assert fired == [f"roll_near_expiry ({condition['condition']} {value}): roll structure"]


class TestExpiryHandling:
    """Short SPXW Jun 7 call and long SPXW Jun 14 call from Wed Jun 5; Jun 7 settles at 16:00 on Friday."""

    def chains(self):
        return [[contract(d, JUN7, 5000, m1, 0.5), contract(d, JUN14, 5000, m2, 0.5)]
                for d, m1, m2 in [(JUN5, 20, 30), (JUN6, 15, 28), (JUN7, 0.05, 25)]]

    def spec(self, handling):
        return body([leg("near", side="short", expiration={"selector": "target_days", "days": 2, "max_days": 12}),
                     leg("far", expiration={"selector": "next_after_leg", "leg": "near"})],
                    expiry_handling=handling)

    def run_it(self, handling):
        return run(self.spec(handling), [JUN5, JUN6, JUN7], self.chains(), index=[5000, 5010, 5020])

    def test_close_structure(self):
        outcome, rec = self.run_it("close_structure")
        near = rows(rec, "position_snapshots", leg_id="near", step=3)[0]
        # settles at 5020 − 5000 = 20: the short pays 1 × 20 × 100 = 2,000
        assert (near["mark_source"], near["cash_flow"]) == ("settlement", pytest.approx(-2_000))
        far = rows(rec, "position_snapshots", leg_id="far", step=3)[0]
        assert far["quantity"] == 0 and rec.rows("trades")[-1]["reason"] == "expiry_handling"
        assert rec.rows("structures")[0]["status"] == "closed"

    def test_keep_remaining(self):
        outcome, rec = self.run_it("keep_remaining")
        assert rows(rec, "position_snapshots", leg_id="far", step=3)[0]["quantity"] == 1
        assert rec.rows("structures")[0]["status"] == "open"

    def test_roll_leg(self):
        outcome, rec = self.run_it("roll_leg")
        near = rows(rec, "position_snapshots", leg_id="near", step=3)
        # the settled Jun 7 leg is re-selected: 2 days ± default window → only Jun 14 (6.99 days) is eligible
        assert [(r["expiration"], r["quantity"]) for r in near] == [(JUN7, 0), (JUN14, -1)]
        assert (3, "roll") in events(rec, "roll")


class TestEntries:
    def test_failed_selection_retried_and_several_structures(self):
        spec = body([leg("call", expiration={"selector": "target_days", "days": 18},
                         strike={"selector": "delta", "target": 0.30})],
                    entry={"schedule": "every_n_trading_days", "n": 1, "max_open": 2})
        chains = [[contract(JUN3, JUN21, 5000, 10, 0.50)],  # nothing near 0.30: entry fails, retried next step
                  [contract(JUN4, JUN21, 5000, 10, 0.30)],
                  [contract(JUN5, JUN21, 5000, 10, 0.30)],
                  [contract(JUN6, JUN21, 5000, 10, 0.30)]]
        outcome, rec = run(spec, [JUN3, JUN4, JUN5, JUN6], chains)
        assert events(rec, "selection_failed", "entry") == [(1, "selection_failed"), (2, "entry"), (3, "entry")]
        assert [p["open_structures"] for p in rec.rows("portfolio_snapshots")] == [0, 1, 2, 2]  # max_open 2 (ENG-3)

    def test_sizing_below_one_unit_skips_the_entry(self):
        spec = body([leg("call")], sizing={"method": "notional", "notional": 400_000})  # 0.8 units at 5000 × 100
        outcome, rec = run(spec, [JUN3], [[contract(JUN3, JUN7, 5000, 20, 0.5)]])
        assert events(rec) == [(1, "entry_skipped")] and rec.rows("structures") == []


class TestRunControl:
    def test_progress_and_cancellation_at_a_step_boundary(self):
        spec = body([leg("call")], entry={"schedule": "when_flat"})
        chains = [[contract(d, JUN14, 5000, 30, 0.5)] for d in (JUN3, JUN4, JUN5)]
        seen = []
        outcome, rec = run(spec, [JUN3, JUN4, JUN5], chains, progress=lambda done, total, t: seen.append((done, total)),
                           cancelled=lambda: len(seen) >= 2)
        assert (outcome.status, outcome.steps_completed) == ("cancelled", 2) and seen == [(1, 3), (2, 3)]
        assert len(rec.rows("portfolio_snapshots")) == 2  # results kept up to the last finished step (RUN-22)

    def test_views_must_follow_the_schedule(self):
        from prophetovol.core.errors import ConfigurationError
        with pytest.raises(ConfigurationError, match="does not match"):
            spec = StrategySpec.model_validate(body([leg("call")]))
            view = MarketDataView(1, as_of(JUN4), JUN4, 5000.0, pa.table({"osi_symbol": pa.array([], pa.string())}))
            run_engine(spec, EngineSettings(BookSettings(100, 1e6, fill_model(MidParams(fill_model="mid")))),
                       StepSchedule(steps=[Step(seq=1, day=JUN3, as_of=as_of(JUN3))]), [view], CAL,
                       RunRecorder("r"))
