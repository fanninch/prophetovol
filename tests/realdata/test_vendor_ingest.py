"""Optional licensed-data checks and checkpoint 1 through the CLI (TEST-5, TEST-10).

Set PROPHETOVOL_VENDOR_DATA to an external folder containing spx/spx_2008 and spx/spx_2023.
Raw input is read in place; derived data and the demo home stay in pytest's external temp area.
"""

import csv
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
import pyarrow as pa
import pytest
from click.testing import CliRunner

from prophetovol.cli import main
from prophetovol.core.context import CallContext
from prophetovol.core.records import VersionState
from prophetovol.data.ivolatility import COLUMNS
from prophetovol.pricing.black76 import greeks
from prophetovol.pricing.time import time_to_expiry_years
from prophetovol.runs.service import BacktestService

pytestmark = pytest.mark.realdata
ROOT = Path(__file__).resolve().parents[2]
CTX = CallContext.for_channel("library")


def cli(home, *args, input=None):
    result = CliRunner().invoke(main, ["--home", str(home), *map(str, args)], input=input)
    assert result.exit_code == 0, result.output[-3000:]
    return result.output


@pytest.fixture(scope="module", params=[2008, 2023])
def imported(request, tmp_path_factory):
    configured = os.environ.get("PROPHETOVOL_VENDOR_DATA")
    if not configured:
        pytest.skip("set PROPHETOVOL_VENDOR_DATA to run licensed-data checks")
    root = Path(configured).resolve()
    assert root.is_dir(), "configured PROPHETOVOL_VENDOR_DATA does not exist"
    assert not root.is_relative_to(ROOT), "vendor data must stay outside the repository"
    year = request.param
    folder = root / "spx" / f"spx_{year}"
    if not folder.is_dir():
        pytest.skip(f"optional vendor year is absent: spx/spx_{year}")
    files = sorted(folder.rglob("*.csv"))
    assert files, "vendor year folder contains no CSV files"
    counts = Counter()
    date_column = COLUMNS.index("date")
    for path in files:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            assert tuple(next(reader)) == COLUMNS
            for row in reader:
                counts[row[date_column]] += 1
    expected = {datetime.strptime(day, "%m/%d/%Y").date(): count for day, count in counts.items()}
    assert expected and all(d.year == year for d in expected)
    home = tmp_path_factory.mktemp(f"vendor-{year}") / "home"
    assert not home.resolve().is_relative_to(ROOT), "derived vendor data must stay outside the repository"
    output = cli(home, "data", "import", folder, "--commit", "replace")
    import_id = re.search(r"Import: (imp_\w+)", output).group(1)
    print(f"Vendor {year}: {sum(expected.values()):,} rows, {len(expected)} dates, {len(files)} files; CLI import succeeded")
    return home, import_id, year, expected, folder


def test_vendor_counts_quality_and_coverage(imported):
    home, import_id, year, expected, _ = imported
    with BacktestService.open(home) as svc:
        record = svc.get_import(import_id)
        assert record.rows == sum(expected.values())
        report = svc.quality_report(import_id)
        assert report.rows == record.rows and report.dates == len(expected) and not report.errors
        versions = svc.data_versions("SPX", import_id, [VersionState.ACTIVE])
        assert {v.as_of_date: v.contracts for v in versions} == expected
        coverage = svc.coverage("SPX", min(expected), max(expected), CTX)
        assert {d.day for d in coverage.days if d.snapshots} == set(expected)
        assert sum(m.contracts for m in coverage.months) == record.rows
        missing = set(svc.calendar.sessions_in_range(min(expected), max(expected))) - set(expected)
        assert sum(m.missing_days for m in coverage.months) == len(missing)
    assert "Quality:" in cli(home, "data", "quality", import_id)
    assert str(year) in cli(home, "data", "coverage", "--underlying", "SPX")


def test_vendor_derived_columns_and_delta_conventions(imported):
    home, import_id, year, expected, _ = imported
    days = sorted(expected)
    sample_days = sorted({days[i] for i in [0, len(days)//4, len(days)//2, 3*len(days)//4, len(days)-1]})
    with BacktestService.open(home) as svc:
        table = pa.concat_tables([svc.import_snapshot(import_id, day) for day in sample_days])
    values = {name: table[name].to_numpy(zero_copy_only=False) for name in
              ["forward", "strike", "time_to_expiry_years", "iv", "delta", "vendor_delta", "vendor_forward", "parity_forward"]}
    t = values["time_to_expiry_years"]
    calculated_t = np.array([time_to_expiry_years(a, e) for a, e in
                             zip(table["as_of_local"].to_pylist(), table["expiry_local"].to_pylist())])
    np.testing.assert_array_equal(t, calculated_t)
    valid = (t > 0) & (values["iv"] > 0) & (values["forward"] > 0) & np.isfinite(values["delta"])
    call = np.array(table["option_type"].to_pylist()) == "call"
    assert valid.sum() > 100
    delta = greeks(values["forward"][valid], values["strike"][valid], t[valid], values["iv"][valid], call[valid]).delta
    assert set(table["root"].to_pylist()) <= {"SPX", "SPXW"}
    assert len(set(table["osi_symbol"].to_pylist())) > 0
    settlements = table["settlement_date"].to_pylist()
    expirations = table["expiration"].to_pylist()
    assert all(s <= e for s, e in zip(settlements, expirations))
    if year < 2018:
        np.testing.assert_allclose(values["delta"][valid], delta, atol=1e-12, rtol=0)
        assert set(table["greeks_source"].to_pylist()) == {"recomputed"}
        assert any(len(s) == 5 for s in table["vendor_symbol"].to_pylist())
        assert any(e.weekday() == 5 and s < e for s, e in zip(settlements, expirations))
        assert "parity" in table["forward_source"].to_pylist()
    else:
        assert set(table["greeks_source"].to_pylist()) == {"vendor"}
        np.testing.assert_array_equal(values["delta"][valid], values["vendor_delta"][valid])
        error = np.abs(delta[call[valid]] - values["vendor_delta"][valid][call[valid]])
        median = float(np.median(error))
        assert median < 0.00001, f"median vendor call delta error {median} exceeds TEST-5"
        parity = np.isfinite(values["parity_forward"]) & (values["vendor_forward"] > 0)
        assert parity.sum() > 100
        relative = np.abs(values["parity_forward"][parity] / values["vendor_forward"][parity] - 1)
        assert np.median(relative) < 0.01  # sanity bound, not a calibration assumption
        print(f"Vendor {year}: median call delta error {median:.9g}; median parity difference {np.median(relative)*10000:.4g} bp")


def test_checkpoint_overlap_delete_and_purge(imported):
    home, import_id, year, expected, folder = imported
    # Re-import one vendor file to exercise overlap without copying licensed input.
    overlap_file = sorted(folder.rglob("*.csv"))[0]
    output = cli(home, "data", "import", overlap_file, "--commit", "ask", input="add-new\n")
    second = re.search(r"Import: (imp_\w+)", output).group(1)
    with BacktestService.open(home) as svc:
        overlaps = len(svc.data_versions("SPX", second))
    assert overlaps > 0 and f"Overlap: {overlaps} of {overlaps}" in output and "Activated 0 snapshots" in output
    assert "Purge completed" in cli(home, "data", "purge", "--import-id", second, "--yes")
    day = min(expected).isoformat()
    assert "Delete completed: 1" in cli(home, "data", "delete", "--underlying", "SPX", "--from", day, "--to", day, input="y\n")
    assert "Purge completed: 1" in cli(home, "data", "purge", "--underlying", "SPX", "--from", day, "--to", day, input="y\n")
    with BacktestService.open(home) as svc:
        assert svc.import_snapshot(import_id, min(expected)).num_rows == 0
        assert len(svc.data_versions("SPX", states=[VersionState.ACTIVE])) == len(expected)-1
    print("Checkpoint 1: reviewed quality and overlap, added new dates only, viewed coverage, confirmed delete and purge")
