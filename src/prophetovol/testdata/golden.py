"""Tiny, hand-checkable option chains for the golden engine tests (TEST-1).

A golden test states every quote and greek it relies on explicitly, in round numbers, so its
expected results can be worked out by hand. These helpers build such rows in the vendor's format
and write them to a file that goes through the ordinary ingest, so the tests exercise the real path.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from prophetovol.data.ivolatility import COLUMNS, format_date, osi_symbol


@dataclass(frozen=True)
class VendorRow:
    """One row of a vendor file, with every value given explicitly.

    :param day: The snapshot date.
    :param index_level: The index close (``adjusted close``).
    :param root: The option root, for example ``SPXW``.
    :param expiration: The expiration date.
    :param strike: The strike.
    :param call: True for a call, False for a put.
    :param bid: The bid.
    :param ask: The ask.
    :param iv: The implied vol (−1 on the settlement date, as the vendor writes it).
    :param delta: The vendor delta.
    :param forward: ``stock price for iv``; the index level when omitted.
    :param gamma: The vendor gamma.
    :param vega: The vendor vega (per vol point).
    :param theta: The vendor theta (per calendar day).
    :param flagged: Whether the ``*`` flag is set.
    :param volume: Volume.
    :param open_interest: Open interest.
    """

    day: date
    index_level: float
    root: str
    expiration: date
    strike: float
    call: bool
    bid: float
    ask: float
    iv: float
    delta: float
    forward: float | None = None
    gamma: float = 0.0
    vega: float = 0.0
    theta: float = 0.0
    flagged: bool = False
    volume: int = 0
    open_interest: int = 0

    def cells(self) -> list[str]:
        """The row's 22 cells, as the vendor writes them.

        :returns: The cells in file order.
        """
        mean = 0.0 if self.bid == 0 else (self.bid + self.ask) / 2
        symbol = osi_symbol(self.root, self.expiration, "call" if self.call else "put", self.strike)
        return ["SPX", "CBOE", format_date(self.day), f"{self.index_level:g}", symbol, format_date(self.expiration),
                f"{self.strike:.1f}", "C" if self.call else "P", "E", f"{self.ask:g}", f"{self.bid:g}", f"{mean:g}",
                f"{self.iv:g}", str(self.volume), str(self.open_interest),
                f"{self.forward if self.forward is not None else self.index_level:g}", "*" if self.flagged else "",
                f"{self.delta:g}", f"{self.vega:g}", f"{self.gamma:g}", f"{self.theta:g}", "0"]


def write_rows(rows: list[VendorRow], path: Path) -> Path:
    """Write rows to a vendor-format CSV, newest date first as the vendor does.

    :param rows: The rows.
    :param path: The file to write; its folder is created if needed.
    :returns: The path written.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda r: (-r.day.toordinal(), r.expiration, r.strike, not r.call))
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(COLUMNS)
        writer.writerows(r.cells() for r in ordered)
    return path


@dataclass(frozen=True)
class GoldenChain:
    """A small chain and what it is for.

    :param name: A short name.
    :param description: What the chain sets up, for the test reading it.
    :param rows: Its rows.
    """

    name: str
    description: str
    rows: list[VendorRow] = field(default_factory=list)


def pm_call_to_expiry() -> GoldenChain:
    """A PM-settled call over three days, settling in the money (TEST-1: held to expiry and settled).

    Index 5000, 5010, 5050 on Wed Jun 12 to Fri Jun 14, 2024. One SPXW expiration on Jun 14 with strikes
    4950, 5000 and 5050. The 5000 call is 30.00/31.00 on Wednesday (delta 0.55) and 35.00/36.00 on
    Thursday (delta 0.70); on Friday the index closes at 5050, so it settles at 50.00.

    :returns: The chain.
    """
    wed, thu, fri, exp = date(2024, 6, 12), date(2024, 6, 13), date(2024, 6, 14), date(2024, 6, 14)
    rows: list[VendorRow] = []
    for day, level, quotes in (
        (wed, 5000.0, {4950: (60, 61, 0.80), 5000: (30, 31, 0.55), 5050: (12, 13, 0.25)}),
        (thu, 5010.0, {4950: (66, 67, 0.90), 5000: (35, 36, 0.70), 5050: (10, 11, 0.22)}),
        (fri, 5050.0, {4950: (99, 101, 0.0), 5000: (49, 51, 0.0), 5050: (0, 0.05, 0.0)}),
    ):
        settles = day == exp
        for strike, (bid, ask, delta) in quotes.items():
            rows.append(VendorRow(day, level, "SPXW", exp, float(strike), True, bid, ask,
                                  iv=-1.0 if settles else 0.15, delta=delta))
            put_delta = 0.0 if settles else round(delta - 1.0, 2)
            put_bid = max(0.0, round(bid - (level - strike), 2))
            rows.append(VendorRow(day, level, "SPXW", exp, float(strike), False, put_bid, put_bid + 1.0,
                                  iv=-1.0 if settles else 0.15, delta=put_delta))
    return GoldenChain("pm_call_to_expiry", "A PM-settled call over three days, settling in the money.", rows)
