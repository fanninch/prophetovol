"""The ``prophetovol run`` commands (INT-40, RUN-12, RUN-21, RUN-22)."""

from __future__ import annotations

import json
import re
from datetime import date

import pytest
from click.testing import CliRunner

from prophetovol.cli import main
from prophetovol.testdata.generator import GeneratorConfig, generate


def invoke(home, *args):
    return CliRunner().invoke(main, ["--home", str(home), *map(str, args)])


@pytest.fixture(scope="module")
def home(tmp_path_factory):
    folder = tmp_path_factory.mktemp("run-cli")
    generate(GeneratorConfig(start_date=date(2024, 3, 1), end_date=date(2024, 4, 30)), folder / "data")
    home = folder / "home"
    assert invoke(home, "data", "import", folder / "data", "--commit", "replace").exit_code == 0
    assert invoke(home, "spec", "examples", "--out", folder / "specs").exit_code == 0
    assert invoke(home, "spec", "publish", folder / "specs" / "short_call_hedged.yaml").exit_code == 0
    (folder / "run.yaml").write_text("start_date: 2024-04-01\nend_date: 2024-04-30\ncapital: 1000000\n"
                                     "commission_per_contract: 0.65\nlabel: cli test\n", encoding="utf-8")
    (folder / "bad.yaml").write_text("start_date: 2024-04-01\nend_date: 2024-05-31\ncapital: 0\n", encoding="utf-8")
    return home


def test_preflight(home):
    ok = invoke(home, "run", "preflight", "--spec", "short_call_hedged", "--config", home.parent / "run.yaml")
    assert ok.exit_code == 0 and "Ready: short_call_hedged@1, 22 steps from 2024-04-01 to 2024-04-30." in ok.output
    bad = invoke(home, "run", "preflight", "--spec", "short_call_hedged@1", "--config", home.parent / "bad.yaml")
    assert bad.exit_code != 0 and "config.capital" in bad.output and "the run cannot start: 1 error" in bad.output


def test_start_list_show(home):
    started = invoke(home, "run", "start", "--spec", "short_call_hedged", "--config", home.parent / "run.yaml")
    assert started.exit_code == 0, started.output
    assert "step 22 of 22, as of 2024-04-30" in started.output  # the progress line (stderr is mixed in)
    match = re.search(r"Run (run_\w+) completed: 22 of 22 steps, cumulative P&L \$[-\d,.]+, equity", started.output)
    assert match, started.output
    run_id = match.group(1)
    listed = invoke(home, "run", "list")
    assert listed.exit_code == 0 and run_id in listed.output and "short_call_hedged@1" in listed.output
    shown = invoke(home, "run", "show", run_id, "--structures", "--events")
    assert shown.exit_code == 0
    for words in ("short_call_hedged@1 (hash", "(cli test)", "fill cross_spread, commission $0.65 per contract",
                  "22 data versions read", "Structure  Parent", "hedge_trade"):
        assert words in shown.output, words
    as_json = json.loads(invoke(home, "run", "show", run_id, "--json").output)
    assert as_json["run_id"] == run_id and as_json["status"] == "completed"


def test_errors(home):
    assert "no run 'nope'" in invoke(home, "run", "show", "nope").output
    first = invoke(home, "run", "list").output.splitlines()[1].split()[0]
    cancelled = invoke(home, "run", "cancel", first)
    assert cancelled.exit_code != 0 and "only queued or running runs can be cancelled" in cancelled.output
