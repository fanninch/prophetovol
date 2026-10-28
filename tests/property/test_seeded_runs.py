"""Invariants on many seeded synthetic runs (TEST-2, ENG-33).

Three generator seeds × the three Appendix B examples × three variations of fill model, rounding and
size. The engine checks ENG-33 at the end of every run and fails the run on a violation; these tests
check again on the stored results, which is what a person reads, and add accounting checks the
stored tables must also satisfy.
"""

from __future__ import annotations

import copy
import json
import math
from collections import defaultdict
from datetime import date

import pytest

from prophetovol.core.context import CallContext
from prophetovol.core.records import RunStatus
from prophetovol.engine.invariants import check_invariants
from prophetovol.runs.service import BacktestService
from prophetovol.strategy.io import example_specs
from prophetovol.testdata.generator import GeneratorConfig, generate

CTX = CallContext.for_channel("library")
DATES = {"start_date": date(2024, 1, 16), "end_date": date(2024, 3, 28)}
CAPITAL = 1_000_000.0
M = 100.0

# seed → generator settings; seed 13 keeps the default four weeklies, so some selections fail and retry
SEEDS = {3: {"weekly_count": 8}, 5: {"weekly_count": 8, "index_vol": 0.30}, 13: {}}

VARIATIONS = {
    # the shipped specs as they are: mid fills, no costs, 10 whole units
    "stock": ({"fill_model": "mid"}, None),
    # paying the spread and costs, fractional units from a notional
    "costly_fractional": ({"fill_model": "cross_spread", "commission_per_contract": 0.65, "hedge_cost_bps": 2.0,
                           "rounding": "fractional"}, {"method": "notional", "notional": 1_234_567.0}),
    # part of the spread, whole units rounded down from a notional
    "fraction_whole": ({"fill_model": "mid_plus_fraction", "fraction": 0.3, "rounding": "whole"},
                       {"method": "notional", "notional": 2_345_678.0}),
}


class Stored:
    """A stored run's tables in the shape :func:`check_invariants` reads."""

    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables

    def rows(self, table: str) -> list[dict]:
        return self._tables[table]


@pytest.fixture(scope="module", params=sorted(SEEDS), ids=lambda s: f"seed{s}")
def svc(request, tmp_path_factory):
    seed = request.param
    folder = tmp_path_factory.mktemp(f"seed-{seed}")
    generate(GeneratorConfig(start_date=date(2024, 1, 2), end_date=date(2024, 3, 28), seed=seed, **SEEDS[seed]),
             folder / "data")
    with BacktestService.open(folder / "home") as service:
        job = service.import_files([folder / "data"], CTX)
        service.commit_import(job.result["import_id"], "replace", CTX)
        for doc in example_specs().values():
            service.publish_spec(doc, CTX)
            for name, (_, sizing) in VARIATIONS.items():
                if sizing:
                    variant = copy.deepcopy(doc) | {"id": f"{doc['id']}_{name}", "sizing": sizing}
                    service.publish_spec(variant, CTX)
        yield service


@pytest.mark.parametrize("variation", sorted(VARIATIONS))
@pytest.mark.parametrize("example", sorted(example_specs()))
def test_invariants_hold_on_the_stored_results(svc, example, variation):
    config, sizing = VARIATIONS[variation]
    spec_id = f"{example}_{variation}" if sizing else example
    run = svc.start_run(spec_id, DATES | {"capital": CAPITAL} | config, CTX)
    assert run.status == RunStatus.COMPLETED, run.error
    tables = {t: svc.run_results(run.run_id, t).to_pylist()
              for t in ("position_snapshots", "portfolio_snapshots", "trades", "structures", "events")}
    portfolio, trades, structures = tables["portfolio_snapshots"], tables["trades"], tables["structures"]
    assert len(portfolio) == run.steps_total and trades

    check_invariants(Stored(tables))  # ENG-33, on what was stored

    for snap in portfolio:
        assert snap["equity"] == pytest.approx(CAPITAL + snap["cumulative_pnl"], abs=1e-6)
    # every dollar of P&L belongs to a structure
    assert sum(s["cumulative_pnl"] for s in structures) == pytest.approx(portfolio[-1]["cumulative_pnl"], abs=1e-6)
    # each step's cash flow is its trades' and settlements' (a settlement is an event, not a trade); fees are trades'
    by_step = defaultdict(lambda: [0.0, 0.0])
    for t in trades:
        by_step[t["step"]][0] += t["cash_flow"]
        by_step[t["step"]][1] += t["fees"]
    for e in tables["events"]:
        if e["type"] == "settlement":
            by_step[e["step"]][0] += json.loads(e["details"])["cash_flow"]
    for snap in portfolio:
        cash, fees = by_step.get(snap["step"], (0.0, 0.0))
        assert snap["cash_flow"] == pytest.approx(cash, abs=1e-6) and snap["fees"] == pytest.approx(fees, abs=1e-6)
    # costs as configured
    commission = config.get("commission_per_contract", 0.0)
    for t in trades:
        if t["leg_id"] != "hedge" and t["action"] in ("open", "close"):
            assert t["fees"] == pytest.approx(abs(t["quantity"]) * commission, abs=1e-9)
    if not config.get("hedge_cost_bps"):
        assert all(t["fees"] == 0 for t in trades if t["leg_id"] == "hedge")
    # units as the sizing and rounding say, at each entry
    index = {snap["step"]: snap["index_level"] for snap in portfolio}
    for s in structures:
        if s["parent_id"] is None:
            raw = sizing["notional"] / (index[s["opened_step"]] * M) if sizing else 10.0
            expected = math.floor(raw) if config.get("rounding", "whole") == "whole" else raw
            assert s["units"] == pytest.approx(expected, rel=1e-12), s["structure_id"]
