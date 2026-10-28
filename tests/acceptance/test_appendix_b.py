"""Acceptance: the three Appendix B examples end to end on generated data through the service (TEST-11, SPEC-82).

One generated half year (seed 2, eight weeklies listed, so a 45-day target always has an expiration in
reach) is imported once; each shipped example runs from Feb 1 to Jun 28, 2024 with the stock
configuration and is checked against what its description promises, from the stored results.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date

import pytest

from prophetovol.core.context import CallContext
from prophetovol.core.records import RunStatus
from prophetovol.runs.service import BacktestService
from prophetovol.strategy.io import example_specs
from prophetovol.testdata.generator import GeneratorConfig, generate

CTX = CallContext.for_channel("library")
CONFIG = {"start_date": date(2024, 2, 1), "end_date": date(2024, 6, 28), "capital": 1_000_000,
          "commission_per_contract": 0.65}
STEPS = 103  # trading days from Feb 1 to Jun 28, 2024
M = 100.0  # SPX multiplier


class Run:
    """One stored run's tables, grouped for the checks."""

    def __init__(self, svc: BacktestService, spec_id: str):
        self.record = svc.start_run(spec_id, CONFIG, CTX)
        tables = {t: svc.run_results(self.record.run_id, t).to_pylist()
                  for t in ("position_snapshots", "portfolio_snapshots", "trades", "structures", "events")}
        self.positions, self.portfolio = tables["position_snapshots"], tables["portfolio_snapshots"]
        self.trades, self.events = tables["trades"], tables["events"]
        self.structures = {s["structure_id"]: s for s in tables["structures"]}
        for e in self.events:
            e["details"] = json.loads(e["details"]) if isinstance(e["details"], str) else e["details"]
        self.by_step_structure: dict[tuple[int, str], list[dict]] = defaultdict(list)
        for p in self.positions:
            self.by_step_structure[(p["step"], p["structure_id"])].append(p)

    def held(self):
        """Option positions held at the end of each step: (step, structure, rows with a quantity)."""
        for (step, sid), rows in sorted(self.by_step_structure.items()):
            legs = [r for r in rows if r["leg_id"] != "hedge" and r["quantity"] != 0]
            if legs:
                yield step, sid, legs, rows

    def net_delta_per_unit(self, sid: str, rows: list[dict]) -> float:
        """SPEC-61's measure from the snapshot: (Σ q·δ + h/m) / N = Σ dollar delta / (S·m·N)."""
        return sum(r["dollar_delta"] for r in rows) / (rows[0]["index_level"] * M * self.structures[sid]["units"])

    def fired(self) -> list[tuple[int, str, dict]]:
        """Every condition that fired a trigger: (step, structure, {condition, value})."""
        return [(e["step"], e["structure_id"], c) for e in self.events if e["type"] == "trigger_fired"
                for f in e["details"]["fired"] for c in f["conditions"]]

    def of_type(self, *types: str) -> list[dict]:
        return [e for e in self.events if e["type"] in types]


@pytest.fixture(scope="module")
def runs(tmp_path_factory) -> dict[str, Run]:
    folder = tmp_path_factory.mktemp("appendix-b")
    generate(GeneratorConfig(start_date=date(2024, 1, 2), end_date=date(2024, 6, 28), seed=2, weekly_count=8),
             folder / "data")
    with BacktestService.open(folder / "home") as svc:
        job = svc.import_files([folder / "data"], CTX)
        svc.commit_import(job.result["import_id"], "replace", CTX)
        for doc in example_specs().values():
            svc.publish_spec(doc, CTX)
        yield {spec_id: Run(svc, spec_id) for spec_id in example_specs()}


@pytest.mark.parametrize("spec_id", ["short_call_hedged", "long_butterfly_60d", "put_diagonal_banded"])
def test_each_example_completes_with_its_accounting(runs, spec_id):
    run = runs[spec_id]
    assert (run.record.status, run.record.steps_completed, run.record.partial) == (RunStatus.COMPLETED, STEPS, False)
    assert len(run.portfolio) == STEPS and run.trades and run.structures
    # nothing was left undone that the checks below rely on: every selection and order went through
    assert not run.of_type("selection_failed", "order_not_filled", "forced_close")
    total = sum(s["cumulative_pnl"] for s in run.structures.values())
    assert total == pytest.approx(run.portfolio[-1]["cumulative_pnl"], abs=1e-6)
    assert run.record.final_equity == pytest.approx(CONFIG["capital"] + run.record.final_pnl)


class TestExample1ShortCallHedged:
    """Short a 30-delta 45-day call; hedge to flat at every step; roll on |delta| > 0.50 or < 0.15, or 15 days."""

    def test_hedged_to_flat_after_every_step(self, runs):
        run = runs["short_call_hedged"]
        held = list(run.held())
        assert len(held) == STEPS  # a structure is held at every step: rolls replace the leg the same step
        for step, sid, _, rows in held:
            assert run.net_delta_per_unit(sid, rows) == pytest.approx(0.0, abs=1e-9), step
        hedge_steps = {t["step"] for t in run.trades if t["leg_id"] == "hedge"}
        assert hedge_steps == set(range(1, STEPS + 1))  # deltas move every day, so the hedge trades every day

    def test_rolled_on_each_of_its_three_conditions(self, runs):
        run = runs["short_call_hedged"]
        fired = run.fired()
        by_condition = defaultdict(list)
        for _, _, c in fired:
            by_condition[c["condition"]].append(c["value"])
        assert set(by_condition) == {"leg_abs_delta_above", "leg_abs_delta_below", "leg_days_to_expiry_at_or_below"}
        assert all(v > 0.50 for v in by_condition["leg_abs_delta_above"])
        assert all(v < 0.15 for v in by_condition["leg_abs_delta_below"])
        assert all(v <= 15 for v in by_condition["leg_days_to_expiry_at_or_below"])
        rolls = run.of_type("roll")
        assert len(rolls) == len(run.of_type("trigger_fired")) >= 3
        # a leg roll keeps the structure: one structure for the whole run
        assert list(run.structures) == ["S1"] and run.structures["S1"]["status"] == "open"

    def test_the_held_call_is_always_within_its_roll_limits(self, runs):
        # after each step's rolls, the short call is a fresh one whenever a limit was crossed
        for step, _, legs, _ in runs["short_call_hedged"].held():
            (call,) = legs
            assert call["quantity"] == -10 and call["option_type"] == "call"
            assert 0.15 <= abs(call["delta"]) <= 0.50 and call["days_to_expiry"] > 15, step

    def test_rolled_legs_open_at_the_selection_targets(self, runs):
        run = runs["short_call_hedged"]
        opened = {t["position_key"]: t for t in run.trades if t["leg_id"] == "short_call" and t["action"] == "open"}
        first_rows = {}
        for p in run.positions:
            first_rows.setdefault(p["position_key"], p)
        for key in opened:
            row = first_rows[key]
            assert 35 <= row["days_to_expiry"] <= 55  # target_days 45, default window
            assert abs(row["delta"] - 0.30) < 0.10  # the listed strike nearest delta 0.30, 25 points apart


class TestExample2LongButterfly:
    """A 60-day iron butterfly: short ATM call and put at one strike, long 25-delta wings; roll at 25 days."""

    def test_four_legs_share_one_expiration_and_the_shorts_one_strike(self, runs):
        held = list(runs["long_butterfly_60d"].held())
        assert len(held) == STEPS
        for step, _, legs, _ in held:
            by_leg = {r["leg_id"]: r for r in legs}
            assert set(by_leg) == {"short_call", "short_put", "long_call", "long_put"}, step
            assert len({r["expiration"] for r in legs}) == 1, step
            assert by_leg["short_call"]["strike"] == by_leg["short_put"]["strike"], step
            assert by_leg["long_put"]["strike"] < by_leg["short_put"]["strike"] < by_leg["long_call"]["strike"], step
            assert {r["leg_id"]: r["quantity"] for r in legs} == {"short_call": -10, "short_put": -10,
                                                                   "long_call": 10, "long_put": 10}, step

    def test_structure_rolls_at_25_days_or_fewer(self, runs):
        run = runs["long_butterfly_60d"]
        fired = run.fired()
        assert fired and all(c["condition"] == "structure_min_days_to_expiry_at_or_below" and c["value"] <= 25
                             for _, _, c in fired)
        # a structure roll closes the structure and opens a child at the same step
        rolls = run.of_type("roll")
        assert len(rolls) == len(fired) >= 3
        for e in rolls:
            child = run.structures[e["structure_id"]]
            parent = run.structures[child["parent_id"]]
            assert child["opened_step"] == parent["closed_step"] == e["step"] and parent["status"] == "closed"
        # and none is held past the limit at the end of a step
        for step, _, legs, _ in run.held():
            assert all(r["days_to_expiry"] > 25 for r in legs), step

    def test_unhedged(self, runs):
        run = runs["long_butterfly_60d"]
        assert not [t for t in run.trades if t["leg_id"] == "hedge"] and not run.of_type("hedge_trade")


class TestExample3PutDiagonalBanded:
    """Short 45-day 25-delta put, long 75-day 20-delta put; net delta per spread in [0, +0.08], reset to +0.03."""

    def test_net_delta_inside_the_band_after_every_hedge(self, runs):
        run = runs["put_diagonal_banded"]
        held = list(run.held())
        assert len(held) == STEPS
        hedged_at = {(t["step"], t["structure_id"]) for t in run.trades if t["leg_id"] == "hedge"}
        assert hedged_at and len(hedged_at) < STEPS  # inside the band, no trade
        for step, sid, _, rows in held:
            measure = run.net_delta_per_unit(sid, rows)
            assert -1e-9 <= measure <= 0.08 + 1e-9, step
            if (step, sid) in hedged_at:
                assert measure == pytest.approx(0.03, abs=1e-9), step  # outside the band: reset to the target

    def test_spread_reestablished_at_15_days(self, runs):
        run = runs["put_diagonal_banded"]
        fired = run.fired()
        assert fired and all(c["condition"] == "leg_days_to_expiry_at_or_below" and c["value"] <= 15
                             for _, _, c in fired)
        rolls = run.of_type("roll")
        assert len(rolls) == len(fired) >= 3
        for e in rolls:
            child = run.structures[e["structure_id"]]
            assert run.structures[child["parent_id"]]["closed_step"] == child["opened_step"] == e["step"]
        for step, _, legs, _ in run.held():
            by_leg = {r["leg_id"]: r for r in legs}
            assert set(by_leg) == {"short_put", "long_put"}, step
            assert by_leg["short_put"]["days_to_expiry"] > 15, step
            assert by_leg["long_put"]["expiration"] > by_leg["short_put"]["expiration"], step
