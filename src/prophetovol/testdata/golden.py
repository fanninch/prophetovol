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


SELECTION_DAYS = (date(2024, 3, 27), date(2024, 3, 28), date(2024, 4, 1), date(2024, 4, 18), date(2024, 4, 19))
"""The snapshot dates of :func:`selection_chain`: around Good Friday (Mar 29, 2024) and the April monthly."""

SELECTION_EXPIRATIONS = (
    ("SPXW", date(2024, 3, 28)), ("SPXW", date(2024, 4, 1)), ("SPXW", date(2024, 4, 3)), ("SPXW", date(2024, 4, 5)),
    ("SPXW", date(2024, 4, 12)), ("SPX", date(2024, 4, 19)), ("SPXW", date(2024, 4, 19)), ("SPXW", date(2024, 4, 22)),
    ("SPXW", date(2024, 4, 26)), ("SPX", date(2024, 5, 17)), ("SPX", date(2024, 6, 21)),
)
"""The listed expirations of :func:`selection_chain`: PM dailies and weeklies (SPXW) and AM monthlies (SPX)."""

_CALL_DELTAS = {5100.0: 0.70, 5150.0: 0.60, 5200.0: 0.50, 5250.0: 0.40, 5300.0: 0.30}


def selection_chain() -> GoldenChain:
    """A chain for the selection tests (TEST-1, selection part), with round numbers throughout.

    Snapshots on :data:`SELECTION_DAYS`, index 5200, and each of :data:`SELECTION_EXPIRATIONS` listed
    until its expiration date with strikes 5100 to 5300, 50 apart. Call deltas are 0.70, 0.60, 0.50,
    0.40 and 0.30 by strike, put deltas the call's minus 1; quotes 10.00/11.00, IV 0.15, forward 5200,
    open interest 0. On an expiration's own date its rows have IV −1 and zero greeks, as the vendor
    writes them. On Mar 27 only, these rows differ:

    * **SPX Jun 21** calls, for the quote filters: 5250 bid 0, ask 0.05 (below ``min_bid``); 5300
      crossed, 12.00/11.00; 5150 flagged ``*``; 5100 open interest 500.
    * **SPXW Apr 26**: forward 5226, and the 5200 and 5250 calls and puts bid 0 (a hole near the forward).
    * **SPXW Apr 12**: forward 5226; the 5200 call's IV −1, so its delta is null after ingest.
    * **SPX May 17**: forward 5212.

    :returns: The chain.
    """
    rows: list[VendorRow] = []
    first = SELECTION_DAYS[0]
    for day in SELECTION_DAYS:
        for root, expiration in SELECTION_EXPIRATIONS:
            if expiration < day:
                continue
            settles = expiration == day
            forward = None
            if day == first and (root, expiration) in (("SPXW", date(2024, 4, 26)), ("SPXW", date(2024, 4, 12))):
                forward = 5226.0
            if day == first and (root, expiration) == ("SPX", date(2024, 5, 17)):
                forward = 5212.0
            for strike, call_delta in _CALL_DELTAS.items():
                for call in (True, False):
                    delta = 0.0 if settles else (call_delta if call else round(call_delta - 1, 2))
                    bid, ask, iv, flagged, oi = 10.0, 11.0, -1.0 if settles else 0.15, False, 0
                    if day == first and (root, expiration) == ("SPX", date(2024, 6, 21)) and call:
                        if strike == 5250:
                            bid, ask = 0.0, 0.05
                        elif strike == 5300:
                            bid, ask = 12.0, 11.0
                        elif strike == 5150:
                            flagged = True
                        elif strike == 5100:
                            oi = 500
                    if day == first and (root, expiration) == ("SPXW", date(2024, 4, 26)) and strike in (5200, 5250):
                        bid = 0.0
                    if day == first and (root, expiration) == ("SPXW", date(2024, 4, 12)) and strike == 5200 and call:
                        iv = -1.0
                    rows.append(VendorRow(day, 5200.0, root, expiration, strike, call, bid, ask, iv, delta,
                                          forward=forward, flagged=flagged, open_interest=oi))
    return GoldenChain("selection", "Expirations and strikes around Good Friday 2024 for every selector.", rows)
