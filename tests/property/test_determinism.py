"""Determinism: two runs of the same inputs give identical stored results (TEST-3, ENG-10).

The same generated files are imported into two homes by two separate processes with different
``PYTHONHASHSEED`` values, so any output that depends on set or hash order would differ. Each process
runs the three Appendix B examples; every stored table must then be equal row for row, apart from run
ids and wall-clock times (decision 14).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date

import pytest

from prophetovol.runs.service import BacktestService
from prophetovol.strategy.io import example_specs
from prophetovol.testdata.generator import GeneratorConfig, generate

TABLES = ("position_snapshots", "portfolio_snapshots", "trades", "structures", "events")

# One process: import, publish the examples, run each; print the run ids as JSON.
SCRIPT = """
import json, sys
from datetime import date
from prophetovol.core.context import CallContext
from prophetovol.runs.service import BacktestService
from prophetovol.strategy.io import example_specs
ctx = CallContext.for_channel("library")
with BacktestService.open(sys.argv[1]) as svc:
    job = svc.import_files([sys.argv[2]], ctx)
    svc.commit_import(job.result["import_id"], "replace", ctx)
    runs = {}
    for doc in example_specs().values():
        svc.publish_spec(doc, ctx)
        config = {"start_date": date(2024, 1, 16), "end_date": date(2024, 3, 28), "capital": 1e6,
                  "fill_model": "cross_spread", "commission_per_contract": 0.65}
        runs[doc["id"]] = svc.start_run(doc["id"], config, ctx).run_id
print(json.dumps(runs))
"""


def run_in_process(home, data, hash_seed: str) -> dict[str, str]:
    env = os.environ | {"PYTHONHASHSEED": hash_seed}
    done = subprocess.run([sys.executable, "-c", SCRIPT, str(home), str(data)], env=env, capture_output=True,
                          text=True, timeout=600)
    assert done.returncode == 0, done.stderr[-3000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def homes(tmp_path_factory):
    folder = tmp_path_factory.mktemp("determinism")
    generate(GeneratorConfig(start_date=date(2024, 1, 2), end_date=date(2024, 3, 28), seed=5, weekly_count=8),
             folder / "data")
    return [(folder / f"home{seed}", run_in_process(folder / f"home{seed}", folder / "data", seed))
            for seed in ("1", "2")]


@pytest.mark.parametrize("spec_id", sorted(example_specs()))
def test_two_processes_store_identical_results(homes, spec_id):
    (home_a, runs_a), (home_b, runs_b) = homes
    with BacktestService.open(home_a) as a, BacktestService.open(home_b) as b:
        ra, rb = a.get_run(runs_a[spec_id]), b.get_run(runs_b[spec_id])
        assert ra.run_id != rb.run_id
        same = ("status", "spec_id", "spec_version", "spec_hash", "config", "config_hash", "underlying_version",
                "data_source_version", "calendar_version", "software_versions", "registry_versions", "steps_total",
                "steps_completed", "last_as_of", "partial", "error", "final_pnl", "final_equity")
        assert {f: getattr(ra, f) for f in same} == {f: getattr(rb, f) for f in same}
        dates = [[(v.as_of_date, v.contracts) for v in s.storage.run_data_versions(r.run_id)]
                 for s, r in ((a, ra), (b, rb))]
        assert dates[0] == dates[1] and dates[0]
        for table in TABLES:
            rows_a = a.run_results(ra.run_id, table).drop(["run_id"]).to_pylist()
            rows_b = b.run_results(rb.run_id, table).drop(["run_id"]).to_pylist()
            assert rows_a, table
            assert rows_a == rows_b, table
