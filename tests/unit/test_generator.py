"""The synthetic data generator (INT-50), TEST-5's generator part, and the golden chain helpers."""

from __future__ import annotations

import csv
import math
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner

from prophetovol.cli import main
from prophetovol.core.types import SettlementStyle
from prophetovol.data.ivolatility import COLUMNS, vendor_root
from prophetovol.pricing import black76
from prophetovol.pricing.time import expiry_dates, local_datetime, time_to_expiry_years
from prophetovol.reference.calendar import nyse_calendar
from prophetovol.reference.defaults import default_underlyings
from prophetovol.testdata.generator import EXPIRY_TIMES, SNAPSHOT_TIME, GeneratorConfig, generate
from prophetovol.testdata.golden import pm_call_to_expiry, write_rows

SPX = default_underlyings()["SPX"]
CAL = nyse_calendar()
CURRENT = GeneratorConfig(start_date=date(2024, 3, 1), end_date=date(2024, 4, 5))   # includes Good Friday Mar 29
OLDER = GeneratorConfig(start_date=date(2008, 3, 3), end_date=date(2008, 3, 28), conventions="older")  # Good Friday Mar 21


def d(text: str) -> date:
    return datetime.strptime(text, "%m/%d/%Y").date()


def read(folder: Path) -> list[dict[str, str]]:
    rows = []
    for path in sorted(folder.glob("data_download*.csv")):
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            assert tuple(reader.fieldnames) == COLUMNS
            rows.extend(reader)
    return rows


@pytest.fixture(scope="module")
def current(tmp_path_factory):
    out = tmp_path_factory.mktemp("current")
    return generate(CURRENT, out), read(out), out


@pytest.fixture(scope="module")
def older(tmp_path_factory):
    out = tmp_path_factory.mktemp("older")
    return generate(OLDER, out), read(out), out


def time_to_expiry(row: dict[str, str]) -> tuple[float, date]:
    style = SPX.root(vendor_root(row["option symbol"])).settlement_style
    e = expiry_dates(d(row["expiration"]), style, EXPIRY_TIMES[SettlementStyle(style)], CAL, "America/New_York")
    return time_to_expiry_years(local_datetime(d(row["date"]), SNAPSHOT_TIME), e.expiry_local), e.settlement_date


class TestFormat:
    def test_dates_are_the_sessions_newest_first(self, current):
        summary, rows, _ = current
        dates = list(dict.fromkeys(d(r["date"]) for r in rows))
        assert dates == sorted(CAL.sessions_in_range(CURRENT.start_date, CURRENT.end_date), reverse=True)
        assert summary.dates == len(dates) and summary.rows == len(rows)

    def test_one_underlying_european_and_parseable(self, current):
        _, rows, _ = current
        assert {r["symbol"] for r in rows} == {"SPX"} and {r["style"] for r in rows} == {"E"}
        for r in rows[:500]:
            for col in ("adjusted close", "strike", "ask", "bid", "mean price", "iv", "stock price for iv", "delta"):
                float(r[col])
            assert r["*"] in ("", "*")

    def test_osi_symbols_and_roots(self, current):
        _, rows, _ = current
        osi = re.compile(r"^(SPX   |SPXW  )\d{6}[CP]\d{8}$")
        assert all(osi.match(r["option symbol"]) for r in rows)
        assert {vendor_root(r["option symbol"]) for r in rows} == {"SPX", "SPXW"}

    def test_am_monthlies_on_third_fridays_and_pm_weeklies_and_dailies(self, current):
        _, rows, _ = current
        by_root = {root: {d(r["expiration"]) for r in rows if vendor_root(r["option symbol"]) == root}
                   for root in ("SPX", "SPXW")}
        assert date(2024, 3, 15) in by_root["SPX"] and date(2024, 4, 19) in by_root["SPX"]
        assert all(e.weekday() == 4 for e in by_root["SPX"])
        weekdays = {e.weekday() for e in by_root["SPXW"]}
        assert weekdays == {0, 1, 2, 3, 4}  # dailies Monday to Thursday, weeklies on Fridays
        assert date(2024, 3, 28) in by_root["SPXW"] and date(2024, 3, 29) not in by_root["SPXW"]  # Good Friday

    def test_contracts_are_unique_per_date(self, current):
        _, rows, _ = current
        keys = Counter((r["date"], vendor_root(r["option symbol"]), r["expiration"], r["strike"], r["call/put"]) for r in rows)
        assert max(keys.values()) == 1
        assert max(Counter((r["date"], r["option symbol"]) for r in rows).values()) == 1

    def test_strikes_are_fixed_per_expiration(self, current):
        _, rows, _ = current
        grids: dict[str, set[str]] = {}
        for r in rows:
            grids.setdefault((r["expiration"], vendor_root(r["option symbol"])), {}).setdefault(r["date"], set()).add(r["strike"])
        for per_day in grids.values():
            assert len({frozenset(s) for s in per_day.values()}) == 1


class TestVendorQuirks:
    def test_settlement_date_rows_have_iv_minus_one_and_zero_greeks(self, current):
        _, rows, _ = current
        settling = [r for r in rows if d(r["date"]) == time_to_expiry(r)[1]]
        assert settling
        assert all(r["iv"] == "-1" and r["delta"] == r["vega"] == r["gamma"] == r["theta"] == "0" for r in settling)
        live = [r for r in rows if d(r["date"]) < time_to_expiry(r)[1]]
        assert all(float(r["iv"]) > 0 for r in live)

    def test_mean_price_is_zero_when_the_bid_is_zero(self, current):
        _, rows, _ = current
        zero_bid = [r for r in rows if float(r["bid"]) == 0]
        assert zero_bid and all(r["mean price"] == "0" for r in zero_bid)

    def test_quirk_rates(self, current):
        summary, rows, _ = current
        live = [r for r in rows if r["iv"] != "-1"]
        crossed = sum(float(r["bid"]) > float(r["ask"]) for r in live)
        zero = sum(float(r["ask"]) == 0 for r in live)
        flagged = sum(r["*"] == "*" for r in rows)
        assert (crossed, zero, flagged) == (summary.crossed_quotes, summary.zero_asks, summary.flagged)
        for observed, share, n in ((crossed, CURRENT.crossed_quote_share, len(live)),
                                   (zero, CURRENT.zero_ask_share * (1 - CURRENT.crossed_quote_share), len(live)),
                                   (flagged, CURRENT.flagged_share, len(rows))):
            expected = share * n
            assert abs(observed - expected) <= 4 * math.sqrt(expected) + 2


class TestGreeksReproduce:
    """TEST-5: Black-76 at the convention's time to expiry reproduces the generator's greeks exactly."""

    @staticmethod
    def check(rows, forward_of, delta_discount_of):
        """Recompute in the internal conventions, then apply the vendor's delta discount (the generator's job)."""
        live = [r for r in rows if r["iv"] != "-1"]
        assert live
        for r in live:
            t, _ = time_to_expiry(r)
            g = black76.greeks(forward_of(r, t), float(r["strike"]), t, float(r["iv"]), r["call/put"] == "C")
            g = g._replace(delta=g.delta * delta_discount_of(t))
            for name in ("delta", "gamma", "vega", "theta"):
                assert abs(round(float(getattr(g, name)), 6) - float(r[name])) <= 1e-9, (name, r)

    def test_current_conventions(self, current):
        _, rows, _ = current
        self.check(rows, lambda r, t: float(r["stock price for iv"]), lambda t: 1.0)

    def test_older_conventions(self, older):
        _, rows, _ = older
        carry, rate = OLDER.rate - OLDER.dividend_yield, OLDER.rate
        self.check(rows, lambda r, t: float(r["adjusted close"]) * math.exp(carry * t), lambda t: math.exp(-rate * t))


class TestOlderConventions:
    def test_five_character_codes_with_configured_roots(self, older):
        _, rows, _ = older
        assert all(len(r["option symbol"]) == 5 for r in rows)
        roots = {vendor_root(r["option symbol"]) for r in rows}
        assert roots <= set(SPX.roots) and {"SPX", "SPT", "SXZ", "SKQ", "SZQ"} <= roots
        assert roots & {"JXA", "JXB", "JXD", "JXE"}

    def test_one_code_names_two_contracts_but_contracts_are_unique(self, older):
        _, rows, _ = older
        assert max(Counter((r["date"], r["option symbol"]) for r in rows).values()) >= 2
        keys = Counter((r["date"], r["expiration"], r["strike"], r["call/put"]) for r in rows)
        assert max(keys.values()) == 1

    def test_saturday_dated_monthlies_settle_friday_or_thursday(self, older):
        _, rows, _ = older
        saturdays = {d(r["expiration"]) for r in rows if d(r["expiration"]).weekday() == 5}
        assert date(2008, 3, 22) in saturdays  # Good Friday 2008-03-21: settles Thursday the 20th
        last_row = max(d(r["date"]) for r in rows if r["expiration"] == "03/22/2008")
        assert last_row == date(2008, 3, 20)
        assert all(r["iv"] == "-1" for r in rows if r["expiration"] == "03/22/2008" and r["date"] == "03/20/2008")

    def test_single_price_per_date_and_discounted_deltas(self, older):
        _, rows, _ = older
        assert all(r["stock price for iv"] == r["adjusted close"] for r in rows)
        pairs = {}
        for r in rows:
            if r["iv"] != "-1":
                pair = pairs.setdefault((r["date"], r["expiration"], r["strike"]), {"t": time_to_expiry(r)[0]})
                pair[r["call/put"]] = float(r["delta"])
        checked = 0
        for pair in pairs.values():
            if "C" in pair and "P" in pair:  # call delta - put delta = D = exp(-rT), to the file's rounding
                assert pair["C"] - pair["P"] == pytest.approx(math.exp(-OLDER.rate * pair["t"]), abs=2e-6)
                checked += 1
        assert checked > 1000

    def test_integer_strikes(self, older):
        _, rows, _ = older
        assert all("." not in r["strike"] for r in rows)


class TestDeterminismAndFiles:
    def test_same_seed_same_bytes_and_different_seed_differs(self, tmp_path):
        small = GeneratorConfig(start_date=date(2024, 6, 3), end_date=date(2024, 6, 7))
        generate(small, tmp_path / "a")
        generate(small, tmp_path / "b")
        generate(small.model_copy(update={"seed": 8}), tmp_path / "c")
        a, b, c = ((tmp_path / x / "data_download.csv").read_bytes() for x in "abc")
        assert a == b and a != c

    def test_split_into_several_files_at_date_boundaries(self, tmp_path):
        summary = generate(CURRENT.model_copy(update={"rows_per_file": 5000}), tmp_path)
        assert len(summary.files) > 1
        assert summary.files[:2] == ["data_download.csv", "data_download2.csv"]
        dates_per_file = []
        for name in summary.files:
            with open(tmp_path / name, newline="") as fh:
                dates_per_file.append({r["date"] for r in csv.DictReader(fh)})
        for i, a in enumerate(dates_per_file):
            for b in dates_per_file[i + 1:]:
                assert not a & b
        assert sum(len(s) for s in dates_per_file) == summary.dates

    def test_rejects_reversed_range(self):
        with pytest.raises(ValueError, match="end_date"):
            GeneratorConfig(start_date=date(2024, 6, 7), end_date=date(2024, 6, 3))

    def test_cli(self, tmp_path):
        result = CliRunner().invoke(main, ["testdata", "generate", "--out", str(tmp_path), "--start", "2024-06-03",
                                           "--end", "2024-06-04", "--conventions", "older"])
        assert result.exit_code == 0, result.output
        assert "rows for 2 dates" in result.output and (tmp_path / "data_download.csv").is_file()


class TestGolden:
    def test_pm_call_chain_round_trips_through_the_vendor_format(self, tmp_path):
        chain = pm_call_to_expiry()
        path = write_rows(chain.rows, tmp_path / "golden.csv")
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 18 and rows[0]["date"] == "06/14/2024"
        call = [r for r in rows if r["date"] == "06/12/2024" and r["strike"] == "5000.0" and r["call/put"] == "C"][0]
        assert (call["bid"], call["ask"], call["delta"], call["option symbol"]) == ("30", "31", "0.55", "SPXW  240614C05000000")
        friday = [r for r in rows if r["date"] == "06/14/2024"]
        assert all(r["iv"] == "-1" for r in friday) and {r["adjusted close"] for r in friday} == {"5050"}
