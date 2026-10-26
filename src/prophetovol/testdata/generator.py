"""Synthetic option data in the exact ivolatility format (INT-50), for tests and the demo.

The generator writes the vendor's 22-column CSV for a synthetic SPX-like index:

* a seeded index path (geometric Brownian motion);
* listed expirations: AM-settled monthlies and PM-settled weeklies and dailies;
* strike grids fixed per expiration from when it is first listed, so held contracts keep appearing;
* implied vols from a simple skew-and-term model;
* Black-76 prices and greeks at the vendor's time convention (CONV-1, CONV-3), with bid-ask spreads
  from a spread model;
* the vendor's expiration-day conventions (IV −1 and zero greeks on the settlement date, ``mean price``
  0 when the bid is 0), and configurable shares of crossed quotes, zero asks and flagged rows.

Two conventions are available (requirements v6, DATA-2, DATA-14):

* ``current`` (the vendor from Jun 25, 2018): OSI symbols, roots ``SPX`` and ``SPXW``, a per-series
  forward in ``stock price for iv``, undiscounted deltas;
* ``older`` (the vendor before 2010 and its pre-2018 methodology): five-character OPRA codes, historical
  roots, Saturday-dated AM monthlies, ``JX*`` weeklies, old quarterly roots (two Decembers under one
  root, so one code names two contracts on a date, as in the real files), one underlying price per
  date in ``stock price for iv``, and discounted deltas.

The generator writes vendor files, so it converts from the internal conventions to the vendor's
(the reverse of an ingest adapter, DATA-15): greeks are computed with Black-76 in the internal
conventions (CONV-10), and in the older conventions the delta is then discounted as the vendor's
were before Jun 25, 2018. Greeks are computed from the rounded values written to the file (IV to
6 decimals, forward to 3, index level to 2), so recomputing them from the file reproduces them to
the file's rounding (TEST-5).
The output for a given configuration is identical on every run (same seed, same bytes).
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import date, time, timedelta
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from prophetovol.core.types import SettlementStyle
from prophetovol.data.ivolatility import COLUMNS, format_date, osi_symbol
from prophetovol.pricing import black76
from prophetovol.pricing.time import expiry_dates, local_datetime, time_to_expiry_years
from prophetovol.reference.calendar import TradingCalendar, nyse_calendar

SNAPSHOT_TIME = time(16, 15)
"""The vendor's option snapshot time (REF-5)."""

EXPIRY_TIMES = {SettlementStyle.AM: time(9, 30), SettlementStyle.PM: time(16, 0)}
"""SPX expiry times by settlement style (REF-1)."""

TZ = "America/New_York"
"""The exchange's time zone."""

FILE_STEM = "data_download"
"""Output files are named like the vendor's downloads: data_download.csv, data_download2.csv, …"""

_MONTH_CODES_CALL = "ABCDEFGHIJKL"
_MONTH_CODES_PUT = "MNOPQRSTUVWX"


class Conventions(StrEnum):
    """Which vendor conventions to reproduce."""

    CURRENT = "current"
    OLDER = "older"


class GeneratorConfig(BaseModel):
    """What to generate. Every value has a default except the date range."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start_date: date = Field(description="First snapshot date (trading days only are generated).")
    end_date: date = Field(description="Last snapshot date, inclusive.")
    seed: int = Field(default=7, description="Random seed; the same configuration and seed give identical files.")
    conventions: Conventions = Field(default=Conventions.CURRENT,
                                     description="current: the vendor from Jun 2018; older: five-character codes, "
                                                 "historical roots, Saturday expirations, single price, discounted deltas.")
    spot: float = Field(default=4500.0, gt=0, description="Index level on the trading day before the start date.")
    index_vol: float = Field(default=0.18, gt=0, description="Annualized volatility of the simulated index path.")
    rate: float = Field(default=0.04, description="Continuously compounded interest rate used for forwards and discounting.")
    dividend_yield: float = Field(default=0.015, description="Continuous dividend yield used for forwards.")
    atm_vol: float = Field(default=0.16, gt=0, description="Long-dated at-the-money implied volatility.")
    term_premium: float = Field(default=0.04, ge=0,
                                description="Extra at-the-money vol for short expirations, decaying over about three months.")
    skew: float = Field(default=0.12, ge=0,
                        description="Slope of implied vol against standardized log-moneyness ln(K/F)/(σ√T); positive "
                                    "makes downside strikes richer.")
    curvature: float = Field(default=0.02, ge=0, description="Convexity of implied vol in standardized log-moneyness.")
    monthly_count: int = Field(default=4, ge=1, description="AM-settled monthly expirations listed at any time.")
    weekly_count: int = Field(default=4, ge=0, description="PM-settled weekly expirations listed at any time.")
    dailies: bool = Field(default=True,
                          description="List Monday to Thursday PM-settled dailies for the next five trading days "
                                      "(current conventions only).")
    strike_step: float = Field(default=25.0, gt=0, description="Distance between listed strikes, in index points.")
    strike_width_sd: float = Field(default=2.5, gt=0,
                                   description="Strikes span this many standard deviations either side of the forward "
                                               "when an expiration is first listed (at least ±5%).")
    crossed_quote_share: float = Field(default=0.002, ge=0, lt=1, description="Share of live rows written with bid > ask.")
    zero_ask_share: float = Field(default=0.003, ge=0, lt=1, description="Share of live rows written with zero bid and ask.")
    flagged_share: float = Field(default=0.15, ge=0, lt=1, description="Share of rows with the vendor's * flag set.")
    rows_per_file: int | None = Field(default=None, gt=0,
                                      description="Start a new file at the next date boundary after this many rows, as the "
                                                  "vendor splits large downloads; one file when omitted.")

    @model_validator(mode="after")
    def _ordered(self) -> GeneratorConfig:
        """Check the date range is in order.

        :returns: The validated configuration.
        """
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self


class GenerationSummary(BaseModel):
    """What was written."""

    files: list[str] = Field(description="The files written, in order.")
    rows: int = Field(description="Data rows written (excluding headers).")
    dates: int = Field(description="Snapshot dates written.")
    expirations: int = Field(description="Distinct expirations written.")
    crossed_quotes: int = Field(description="Rows written with bid > ask.")
    zero_asks: int = Field(description="Rows written with zero bid and ask.")
    flagged: int = Field(description="Rows with the * flag.")


@dataclass(frozen=True)
class _Expiration:
    """One listed expiration.

    :param expiration: The expiration date as listed.
    :param root: The vendor root it is listed under.
    :param style: Its settlement style.
    :param kind: monthly, weekly, daily or quarterly.
    """

    expiration: date
    root: str
    style: SettlementStyle
    kind: str


def _third_friday(year: int, month: int) -> date:
    """The third Friday of a month.

    :param year: The year.
    :param month: The month.
    :returns: The date.
    """
    first = date(year, month, 1)
    return first + timedelta(days=(4 - first.weekday()) % 7 + 14)


def _months(start: date, count: int) -> list[tuple[int, int]]:
    """Consecutive (year, month) pairs starting at ``start``'s month.

    :param start: Any date in the first month.
    :param count: How many months.
    :returns: The pairs.
    """
    return [((start.year * 12 + start.month - 1 + i) // 12, (start.month - 1 + i) % 12 + 1) for i in range(count)]


def _schedule(config: GeneratorConfig, cal: TradingCalendar) -> dict[str, list[_Expiration]]:
    """Every candidate expiration that could be listed in the run, by kind, in date order.

    :param config: The configuration.
    :param cal: The trading calendar.
    :returns: Expirations by kind.
    """
    horizon = config.end_date + timedelta(days=500)
    months = _months(config.start_date - timedelta(days=31), (horizon.year - config.start_date.year) * 12 + 18)
    older = config.conventions is Conventions.OLDER
    monthly, weekly, daily, quarterly = [], [], [], []
    third_fridays = {_third_friday(y, m) for y, m in months}
    for y, m in months:
        tf = _third_friday(y, m)
        listed = tf + timedelta(days=1) if older else cal.session_on_or_before(tf)
        monthly.append(_Expiration(listed, "SPX", SettlementStyle.AM, "monthly"))
        if older and m in (3, 6, 9, 12):
            last = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
            root = "SKQ" if m == 12 else "SZQ"
            quarterly.append(_Expiration(cal.session_on_or_before(last), root, SettlementStyle.PM, "quarterly"))
    day = config.start_date - timedelta(days=7)
    while day <= horizon:
        if day.weekday() == 4 and day not in third_fridays:
            week = (day.day - 1) // 7
            root = ("JXA", "JXB", "JXC", "JXD", "JXE")[week] if older else "SPXW"
            if root != "JXC":  # the vendor files show JXA, JXB, JXD and JXE only
                weekly.append(_Expiration(cal.session_on_or_before(day), root, SettlementStyle.PM, "weekly"))
        elif not older and config.dailies and day.weekday() < 4 and cal.is_session(day):
            daily.append(_Expiration(day, "SPXW", SettlementStyle.PM, "daily"))
        day += timedelta(days=1)
    return {"monthly": monthly, "weekly": weekly, "daily": daily, "quarterly": quarterly}


class _Generator:
    """One generation run.

    :param config: The configuration.
    """

    def __init__(self, config: GeneratorConfig) -> None:
        self.c = config
        self.cal = nyse_calendar()
        self.older = config.conventions is Conventions.OLDER
        self.rng = np.random.default_rng(config.seed)
        self.schedule = _schedule(config, self.cal)
        self.strikes: dict[_Expiration, np.ndarray] = {}
        self.counts = {"crossed": 0, "zero_ask": 0, "flagged": 0}

    @lru_cache(maxsize=None)
    def dates_of(self, exp: _Expiration) -> tuple[date, date]:
        """Settlement date and expiry clock time of an expiration (CONV-3).

        :param exp: The expiration.
        :returns: Its settlement date and exchange-local expiry.
        """
        d = expiry_dates(exp.expiration, exp.style, EXPIRY_TIMES[exp.style], self.cal, TZ)
        return d.settlement_date, d.expiry_local

    def listed_on(self, day: date) -> list[_Expiration]:
        """The expirations listed on a date, in expiration order.

        :param day: The snapshot date.
        :returns: The expirations.
        """
        def upcoming(kind: str, count: int) -> list[_Expiration]:
            live = [e for e in self.schedule[kind] if self.dates_of(e)[0] >= day]
            return live[:count]

        out = upcoming("monthly", self.c.monthly_count) + upcoming("weekly", self.c.weekly_count)
        if self.schedule["daily"]:
            limit = self.cal.sessions_in_range(day, day + timedelta(days=10))[:5]
            out += [e for e in self.schedule["daily"] if day <= e.expiration <= limit[-1]]
        if self.schedule["quarterly"]:
            quarters = upcoming("quarterly", 3)
            decembers = [e for e in self.schedule["quarterly"] if e.root == "SKQ" and self.dates_of(e)[0] >= day][:2]
            out += sorted(set(quarters) | set(decembers), key=lambda e: e.expiration)
        # One listing per (expiration, root): a holiday-shifted weekly can land on a daily's date.
        unique: dict[tuple[date, str], _Expiration] = {}
        for e in out:
            unique.setdefault((e.expiration, e.root), e)
        return sorted(unique.values(), key=lambda e: (e.expiration, e.root))

    def atm_vol(self, t: float) -> float:
        """At-the-money implied vol for a time to expiry.

        :param t: Time to expiry in years.
        :returns: The vol.
        """
        return self.c.atm_vol + self.c.term_premium * math.exp(-t / 0.25)

    def strike_grid(self, exp: _Expiration, forward: float, t: float) -> np.ndarray:
        """The strikes of an expiration, fixed when it is first listed.

        :param exp: The expiration.
        :param forward: The forward on the listing date.
        :param t: Time to expiry on the listing date, in years.
        :returns: The strikes, ascending.
        """
        if exp not in self.strikes:
            half = max(0.05, self.c.strike_width_sd * self.atm_vol(t) * math.sqrt(max(t, 1 / 365)))
            step = self.c.strike_step
            lo = math.floor(forward * math.exp(-half) / step) * step
            hi = math.ceil(forward * math.exp(half) / step) * step
            self.strikes[exp] = np.arange(lo, hi + step / 2, step)
        return self.strikes[exp]

    def implied_vol(self, forward: float, strikes: np.ndarray, t: float) -> np.ndarray:
        """Implied vols from the skew-and-term model, rounded to 6 decimals as written.

        :param forward: The forward.
        :param strikes: The strikes.
        :param t: Time to expiry in years.
        :returns: The vols.
        """
        atm = self.atm_vol(t)
        x = np.log(strikes / forward) / (atm * math.sqrt(t))
        iv = atm * (1.0 - self.c.skew * x + self.c.curvature * x * x)
        return np.round(np.clip(iv, 0.05, 2.0), 6)

    def quotes(self, mid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Bid and ask from model mids: a spread model on the vendor's ticks.

        :param mid: Model prices.
        :returns: Bids and asks.
        """
        tick = np.where(mid < 3.0, 0.05, 0.10)
        half = np.clip(0.03 * mid, 0.05, 5.0)
        bid = np.maximum(np.floor((mid - half) / tick + 1e-9) * tick, 0.0)
        ask = np.maximum(np.ceil((mid + half) / tick - 1e-9) * tick, tick)
        return np.round(bid, 2), np.round(ask, 2)

    def symbol(self, root: str, expiration: date, is_call: bool, strike: float) -> str:
        """The vendor's option symbol.

        Older five-character codes are the root, a month code (A-L calls, M-X puts) and a strike code
        that wraps every 26 strikes, so the same code can name different contracts.

        :param root: The contract's vendor root.
        :param expiration: The expiration date.
        :param is_call: Call or put.
        :param strike: The strike.
        :returns: A five-character OPRA code (older) or an OSI symbol (current).
        """
        if not self.older:
            return osi_symbol(root, expiration, "call" if is_call else "put", strike)
        month = (_MONTH_CODES_CALL if is_call else _MONTH_CODES_PUT)[expiration.month - 1]
        return f"{root}{month}{chr(65 + int(round(strike / self.c.strike_step)) % 26)}"

    def root_for(self, exp: _Expiration, strike: float, forward: float) -> str:
        """The vendor root of a contract: older monthlies are split across roots by strike range.

        :param exp: The expiration.
        :param strike: The strike.
        :param forward: The forward on the date.
        :returns: The root.
        """
        if self.older and exp.kind == "monthly":
            return "SPT" if strike < 0.95 * forward else "SXZ" if strike > 1.05 * forward else "SPX"
        return exp.root

    def rows_for(self, day: date, spot: float) -> list[list[str]]:
        """Every row of one snapshot date.

        :param day: The snapshot date.
        :param spot: The index close, already rounded to 2 decimals.
        :returns: The rows, in the vendor's order (expiration, strike, call before put).
        """
        rows = []
        as_of = local_datetime(day, SNAPSHOT_TIME)
        carry = self.c.rate - self.c.dividend_yield
        for exp in self.listed_on(day):
            settlement, expiry_local = self.dates_of(exp)
            expired = day >= settlement
            t = time_to_expiry_years(as_of, expiry_local)
            t_list = max(t, 1 / 365)
            fwd_model = spot * math.exp(carry * max(t, 0.0))
            forward = fwd_model if self.older else round(fwd_model, 3)
            strikes = self.strike_grid(exp, forward, t_list)
            n = len(strikes)
            k = np.repeat(strikes, 2)
            calls = np.tile([True, False], n)
            if expired:
                iv = np.full(2 * n, -1.0)
                mid = np.where(calls, np.maximum(spot - k, 0.0), np.maximum(k - spot, 0.0))
                g = black76.Greeks(*(np.zeros(2 * n) for _ in range(4)))
                rho = np.zeros(2 * n)
            else:
                iv = np.repeat(self.implied_vol(forward, strikes, t), 2)
                disc = math.exp(-self.c.rate * t)
                mid = black76.price(forward, k, t, iv, calls, discount=disc)
                g = black76.greeks(forward, k, t, iv, calls)
                if self.older:  # the vendor's deltas before Jun 25, 2018 were discounted
                    g = g._replace(delta=g.delta * disc)
                rho = -t * mid * 0.01
            bid, ask = self.quotes(mid)
            u = self.rng.random((4, 2 * n))
            if not expired:
                crossed = u[0] < self.c.crossed_quote_share
                zero = (u[1] < self.c.zero_ask_share) & ~crossed
                bid = np.where(crossed, ask + 0.05, bid)
                bid, ask = np.where(zero, 0.0, bid), np.where(zero, 0.0, ask)
                self.counts["crossed"] += int(crossed.sum())
                self.counts["zero_ask"] += int(zero.sum())
            flagged = u[2] < self.c.flagged_share
            self.counts["flagged"] += int(flagged.sum())
            volume = (u[3] * 50).astype(int)
            oi = self.rng.integers(0, 5000, 2 * n)
            vendor_fwd = round(spot, 2) if self.older else forward
            for i in range(2 * n):
                strike = float(k[i])
                vmid = 0.0 if bid[i] == 0 else round((bid[i] + ask[i]) / 2, 4)
                rows.append([
                    "SPX", "CBOE", format_date(day), _num(spot, 2),
                    self.symbol(self.root_for(exp, strike, forward), exp.expiration, bool(calls[i]), strike),
                    format_date(exp.expiration), _strike(strike, self.older), "C" if calls[i] else "P", "E",
                    _num(ask[i], 2), _num(bid[i], 2), _num(vmid, 4), _num(iv[i], 6),
                    str(int(volume[i])), str(int(oi[i])), _num(vendor_fwd, 3), "*" if flagged[i] else "",
                    _num(g.delta[i], 6), _num(g.vega[i], 6), _num(g.gamma[i], 6), _num(g.theta[i], 6), _num(rho[i], 6),
                ])
        return rows


def _num(value: float, decimals: int) -> str:
    """Format a number as the vendor does: rounded, without trailing zeros.

    :param value: The number.
    :param decimals: Decimal places to round to.
    :returns: The text, for example ``0.05``, ``4257.4`` or ``-1``.
    """
    text = f"{round(float(value), decimals):.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _strike(strike: float, older: bool) -> str:
    """Format a strike: ``1400.0`` in current files, ``450`` in older ones.

    :param strike: The strike.
    :param older: Whether older conventions apply.
    :returns: The text.
    """
    return _num(strike, 3) if older else f"{strike:.1f}"


def index_path(config: GeneratorConfig) -> list[tuple[date, float]]:
    """The simulated index close on each trading day of the range, rounded to 2 decimals.

    :param config: The configuration.
    :returns: (date, close) pairs, oldest first.
    """
    cal = nyse_calendar()
    days = cal.sessions_in_range(config.start_date, config.end_date)
    rng = np.random.default_rng([config.seed, 1])
    daily_vol = config.index_vol / math.sqrt(252)
    drift = (config.rate - config.dividend_yield) / 252 - 0.5 * daily_vol * daily_vol
    levels = config.spot * np.exp(np.cumsum(drift + daily_vol * rng.standard_normal(len(days))))
    return [(d, round(float(s), 2)) for d, s in zip(days, levels)]


def generate(config: GeneratorConfig, out_dir: Path) -> GenerationSummary:
    """Write synthetic vendor files into a folder.

    Dates are written newest first, as in the vendor's files; a new file starts at the next date
    boundary once ``rows_per_file`` is reached.

    :param config: What to generate.
    :param out_dir: The folder to write into; created if needed. Existing ``data_download*.csv`` files
        in it are replaced.
    :returns: What was written.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob(f"{FILE_STEM}*.csv"):
        old.unlink()
    gen = _Generator(config)
    path = index_path(config)
    per_date = [(day, gen.rows_for(day, spot)) for day, spot in path]
    files: list[str] = []
    rows_total, in_file, writer, handle = 0, 0, None, None
    expirations: set[str] = set()
    try:
        for day, rows in reversed(per_date):
            if writer is None or (config.rows_per_file is not None and in_file >= config.rows_per_file):
                if handle is not None:
                    handle.close()
                name = f"{FILE_STEM}.csv" if not files else f"{FILE_STEM}{len(files) + 1}.csv"
                files.append(name)
                handle = open(out_dir / name, "w", encoding="utf-8", newline="")
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow(COLUMNS)
                in_file = 0
            writer.writerows(rows)
            in_file += len(rows)
            rows_total += len(rows)
            expirations.update(r[5] for r in rows)
    finally:
        if handle is not None:
            handle.close()
    return GenerationSummary(files=files, rows=rows_total, dates=len(per_date), expirations=len(expirations),
                             crossed_quotes=gen.counts["crossed"], zero_asks=gen.counts["zero_ask"],
                             flagged=gen.counts["flagged"])
