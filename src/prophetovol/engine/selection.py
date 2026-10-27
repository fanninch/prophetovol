"""Selecting a structure's contracts at a step (SPEC-3, SPEC-4, SPEC-10 to SPEC-28).

For each leg, in dependency order (SPEC-3):

1. **Eligible contracts** (SPEC-26): the leg's option type and allowed roots; never at or after the
   expiry, and an AM-settled contract never on or after its last trading day (SPEC-15); the spec's
   quote filters (SPEC-28).
2. **The expiration** (SPEC-10 to SPEC-14): the leg's expiration selector chooses among the
   expirations that have eligible contracts and pass its filter.
3. **The strike** (SPEC-20 to SPEC-25): the leg's strike selector chooses among that expiration's
   eligible contracts. Delta-based selectors ignore contracts with a null delta (SPEC-27).

Selection is atomic (SPEC-4): if any leg fails, :func:`select_legs` returns the failure, naming
the leg, its selector and why, and no contract. Distances are compared rounded to 1e-9, so values
equally far from a target tie exactly; ties follow each selector's ``tie_break``, and for the
point-distance selectors (``forward``, ``same_strike_as``, ``strike_offset``) the lower strike.

The implementations are registered here with their parameter models (decision 29).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol

import numpy as np
import pyarrow as pa

from prophetovol.core.types import SettlementStyle
from prophetovol.engine.view import ExpirationInfo, MarketDataView, group_expirations
from prophetovol.registry.catalog import EXPIRATION_SELECTORS, STRIKE_SELECTORS
from prophetovol.registry.params.selection import (AtmParams, DeltaParams, ExpirationFilter, ExpirationTieBreak,
                                                   ForwardParams, NextAfterLegParams, NthExpirationParams, OnNoMatch,
                                                   SameAsLegParams, SameStrikeAsParams, StrikeOffsetParams,
                                                   StrikeTieBreak, TargetDaysParams, TradingDaysOutParams, Weekday)
from prophetovol.strategy.model import Leg, StrategySpec
from prophetovol.strategy.validate import leg_order

_ROUND = 9
_EPS = 1e-9
_WEEKDAYS = list(Weekday)
_SPACING_STRIKES = 10


class SelectionCalendar(Protocol):
    """The trading-calendar lookups selection needs (``reference.calendar.TradingCalendar`` has them)."""

    def is_session(self, day: date) -> bool:
        """Whether ``day`` is a trading day.

        :param day: The date.
        """

    def previous_session(self, day: date) -> date:
        """The last trading day strictly before ``day``.

        :param day: The date.
        """


@dataclass(frozen=True)
class SelectedContract:
    """The contract a leg selected, with its snapshot row at the selection step.

    :param leg_id: The leg.
    :param osi_symbol: The contract's OSI symbol, its identity with the underlying (DATA-2).
    :param root: The normalized root.
    :param expiration: The expiration date.
    :param option_type: ``call`` or ``put``.
    :param strike: The strike.
    :param expiry_timestamp: The expiry instant (UTC).
    :param row: The contract's snapshot row (:data:`~prophetovol.engine.view.ENGINE_COLUMNS`).
    """

    leg_id: str
    osi_symbol: str
    root: str
    expiration: date
    option_type: str
    strike: float
    expiry_timestamp: datetime
    row: dict[str, Any]


@dataclass(frozen=True)
class SelectionIssue:
    """Why a leg could not be selected, or a warning about how it was (SPEC-4, SPEC-25).

    :param leg_id: The leg.
    :param selector: The selector concerned, for example ``strike_selector delta``.
    :param message: What happened, for the event.
    """

    leg_id: str
    selector: str
    message: str


@dataclass(frozen=True)
class SelectionResult:
    """The outcome of selecting some legs at one step.

    :param contracts: The selected contracts by leg id, in selection order; empty when selection failed.
    :param failure: Why selection failed, or None.
    :param warnings: Warnings, for example a strike taken outside tolerance under ``nearest_any``.
    """

    contracts: dict[str, SelectedContract]
    failure: SelectionIssue | None
    warnings: tuple[SelectionIssue, ...]

    @property
    def ok(self) -> bool:
        """Whether every leg was selected.

        :returns: True when selection succeeded.
        """
        return self.failure is None


@dataclass(frozen=True)
class ExpirationContext:
    """What an expiration selector may read besides the eligible expirations.

    :param leg_id: The leg being selected.
    :param selected: Contracts already selected for other legs at this step.
    """

    leg_id: str
    selected: Mapping[str, SelectedContract]


@dataclass(frozen=True)
class StrikeCandidates:
    """One expiration's eligible contracts for a leg, sorted by strike, and its listed strikes.

    :param option_type: ``call`` or ``put``.
    :param strikes: Strikes of the eligible contracts, ascending.
    :param deltas: Their deltas (NaN when null).
    :param forward: The series forward (NaN when null).
    :param listed_strikes: Every strike listed in the expiration, whatever its quote, ascending.
    :param selected: Contracts already selected for other legs at this step.
    """

    option_type: str
    strikes: np.ndarray
    deltas: np.ndarray
    forward: float
    listed_strikes: np.ndarray
    selected: Mapping[str, SelectedContract]


@dataclass(frozen=True)
class StrikePick:
    """A strike selector's answer.

    :param index: Index into the candidates, or None when nothing could be chosen.
    :param message: Why nothing was chosen, or, for a pick outside tolerance, the warning.
    """

    index: int | None
    message: str = ""


# --- eligibility and filters (SPEC-14, SPEC-15, SPEC-26, SPEC-28) --------------------------------


def third_friday(year: int, month: int) -> date:
    """The third Friday of a month.

    :param year: The year.
    :param month: The month.
    :returns: The date.
    """
    fifteenth = date(year, month, 15)
    return fifteenth + timedelta(days=(4 - fifteenth.weekday()) % 7)


def is_standard_monthly(settlement_date: date, calendar: SelectionCalendar) -> bool:
    """Whether a settlement date is a standard monthly's (SPEC-14, plan §7.5 answer 5).

    That is the third Friday of its month, or the trading day before it when that Friday is a holiday;
    the Saturday-dated monthlies before 2015 settle on that Friday and count.

    :param settlement_date: The settlement date (CONV-3).
    :param calendar: The trading calendar.
    :returns: True for a standard monthly, whatever its root.
    """
    friday = third_friday(settlement_date.year, settlement_date.month)
    if settlement_date == friday:
        return True
    return not calendar.is_session(friday) and settlement_date == calendar.previous_session(friday)


def passes_filter(info: ExpirationInfo, flt: ExpirationFilter, calendar: SelectionCalendar) -> bool:
    """Whether an expiration passes an expiration filter (SPEC-14).

    :param info: The expiration.
    :param flt: The filter.
    :param calendar: The trading calendar.
    :returns: True when every condition the filter states holds.
    """
    if flt.standard_monthly_only and not is_standard_monthly(info.settlement_date, calendar):
        return False
    if flt.weekdays and _WEEKDAYS[info.expiration.weekday()] not in flt.weekdays:
        return False
    if flt.roots and info.root not in flt.roots:
        return False
    if flt.settlement_styles and SettlementStyle(info.settlement_style) not in flt.settlement_styles:
        return False
    return True


def eligible_rows(view: MarketDataView, leg: Leg, spec: StrategySpec) -> pa.Table:
    """The contracts a leg may select at the view's step (SPEC-15, SPEC-26, SPEC-28).

    :param view: The step's market data.
    :param leg: The leg.
    :param spec: Its spec, for the quote filters.
    :returns: The eligible rows.
    """
    if len(view) == 0:
        return view.table()
    q = spec.selection
    as_of = np.datetime64(view.as_of.replace(tzinfo=None), "us")
    expiry = view.column("expiry_timestamp").astype("datetime64[us]")
    mask = (view.column("option_type") == str(leg.option_type)) & (expiry > as_of)
    am_last_day = (view.column("settlement_style") == "AM") & (
        view.column("last_trading_date").astype("datetime64[D]") <= np.datetime64(view.as_of_date, "D"))
    mask &= ~am_last_day
    if leg.roots:
        mask &= np.isin(view.column("root"), leg.roots)
    bid = view.column("bid").astype(float)
    ask = view.column("ask").astype(float)
    if q.require_valid_quote:
        with np.errstate(invalid="ignore"):
            mask &= (ask > 0) & (bid >= 0) & (ask >= bid)
    with np.errstate(invalid="ignore"):
        mask &= bid >= q.min_bid - _EPS
    if q.min_open_interest > 0:
        with np.errstate(invalid="ignore"):
            mask &= view.column("open_interest").astype(float) >= q.min_open_interest
    if q.exclude_vendor_flagged:
        mask &= view.column("vendor_flag") != True  # noqa: E712 - nulls count as not flagged
    return view.table().filter(pa.array(mask))


def _filtered(options: list[ExpirationInfo], params: Any, calendar: SelectionCalendar) -> list[ExpirationInfo]:
    """The options that pass a selector's own filter, when it has one.

    :param options: Eligible expirations.
    :param params: The selector's parameters.
    :param calendar: The trading calendar.
    :returns: The options left.
    """
    flt = getattr(params, "filter", None)
    return options if flt is None else [o for o in options if passes_filter(o, flt, calendar)]


def _nearest_expiration(options: list[ExpirationInfo], distance: list[float], tie_break: ExpirationTieBreak
                        ) -> ExpirationInfo:
    """The option with the smallest distance, ties broken by the tie-break.

    :param options: Options ordered by expiry, then root.
    :param distance: Their distances.
    :param tie_break: ``later`` or ``earlier``.
    :returns: The chosen option.
    """
    best = min(round(d, _ROUND) for d in distance)
    tied = [o for o, d in zip(options, distance) if round(d, _ROUND) == best]
    return tied[-1] if tie_break is ExpirationTieBreak.LATER else tied[0]


def _describe(options: list[ExpirationInfo]) -> str:
    """A short list of expirations for a message.

    :param options: The expirations.
    :returns: For example ``SPXW 2024-04-01 (4.99 days, 2 trading days), …``.
    """
    shown = ", ".join(f"{o.root} {o.expiration} ({o.days_to_expiry:.2f} days, {o.trading_days_to_expiry} trading "
                      f"day{'' if o.trading_days_to_expiry == 1 else 's'})" for o in options[:4])
    return (shown + (f" and {len(options) - 4} more" if len(options) > 4 else "")) or "none"


# --- expiration selectors (SPEC-10 to SPEC-13) ---------------------------------------------------


@EXPIRATION_SELECTORS.register(
    "target_days", params=TargetDaysParams, version="1",
    description="Chooses the expiration whose calendar days to expiry (fractional, CONV-1) is nearest days, among "
                "expirations within [min_days, max_days] that pass the filter. Ties go to the later expiration "
                "unless tie_break is earlier. Example: days 45 for a monthly-style strategy; days 0.5 with "
                "max_days 1 for a same-day expiration.")
class TargetDays:
    """The ``target_days`` expiration selector (SPEC-10).

    :param params: Its validated parameters.
    """

    def __init__(self, params: TargetDaysParams) -> None:
        self.params = params

    def choose(self, options: list[ExpirationInfo], ctx: ExpirationContext) -> tuple[ExpirationInfo | None, str]:
        """Choose among eligible expirations that passed the filter.

        :param options: The expirations, ordered by expiry, then root.
        :param ctx: The selection context.
        :returns: The expiration, or None and why.
        """
        low, high = self.params.window()
        inside = [o for o in options if low - _EPS <= o.days_to_expiry <= high + _EPS]
        if not inside:
            return None, (f"no eligible expiration within {low:g}–{high:g} calendar days to expiry "
                          f"(eligible: {_describe(options)})")
        return _nearest_expiration(inside, [abs(o.days_to_expiry - self.params.days) for o in inside],
                                   self.params.tie_break), ""


@EXPIRATION_SELECTORS.register(
    "trading_days_out", params=TradingDaysOutParams, version="1",
    description="Chooses the expiration whose trading days to expiry (CONV-2) equals n, or the nearest within "
                "tolerance trading days, among expirations that pass the filter. Example: n 1 with settlement_styles "
                "[PM] for the next trading day's PM-settled expiration.")
class TradingDaysOut:
    """The ``trading_days_out`` expiration selector (SPEC-11).

    :param params: Its validated parameters.
    """

    def __init__(self, params: TradingDaysOutParams) -> None:
        self.params = params

    def choose(self, options: list[ExpirationInfo], ctx: ExpirationContext) -> tuple[ExpirationInfo | None, str]:
        """Choose among eligible expirations that passed the filter.

        :param options: The expirations, ordered by expiry, then root.
        :param ctx: The selection context.
        :returns: The expiration, or None and why.
        """
        n, tol = self.params.n, self.params.tolerance
        inside = [o for o in options if abs(o.trading_days_to_expiry - n) <= tol]
        if not inside:
            return None, (f"no eligible expiration {n} trading day(s) out (tolerance {tol}; eligible: "
                          f"{_describe(options)})")
        return _nearest_expiration(inside, [abs(o.trading_days_to_expiry - n) for o in inside],
                                   self.params.tie_break), ""


@EXPIRATION_SELECTORS.register(
    "nth_expiration", params=NthExpirationParams, version="1",
    description="Chooses the n-th eligible expiration after the as-of time, counting only expirations that pass "
                "the filter; n 1 is the next one. Example: n 2 with standard_monthly_only for the second monthly.")
class NthExpiration:
    """The ``nth_expiration`` expiration selector (SPEC-12).

    :param params: Its validated parameters.
    """

    def __init__(self, params: NthExpirationParams) -> None:
        self.params = params

    def choose(self, options: list[ExpirationInfo], ctx: ExpirationContext) -> tuple[ExpirationInfo | None, str]:
        """Choose among eligible expirations that passed the filter.

        :param options: The expirations, ordered by expiry, then root.
        :param ctx: The selection context.
        :returns: The expiration, or None and why.
        """
        if len(options) < self.params.n:
            return None, f"only {len(options)} eligible expiration(s), needed the {self.params.n}th"
        return options[self.params.n - 1], ""


@EXPIRATION_SELECTORS.register(
    "same_as_leg", params=SameAsLegParams, version="1",
    description="Uses the same expiration as the referenced leg, which is selected first (SPEC-3).")
class SameAsLeg:
    """The ``same_as_leg`` expiration selector (SPEC-13).

    :param params: Its validated parameters.
    """

    def __init__(self, params: SameAsLegParams) -> None:
        self.params = params

    def choose(self, options: list[ExpirationInfo], ctx: ExpirationContext) -> tuple[ExpirationInfo | None, str]:
        """Use the referenced leg's expiration, if it is eligible for this leg.

        :param options: The expirations, ordered by expiry, then root.
        :param ctx: The selection context.
        :returns: The expiration, or None and why.
        """
        ref = ctx.selected[self.params.leg]
        for o in options:
            if (o.root, o.expiration) == (ref.root, ref.expiration):
                return o, ""
        return None, f"{ref.root} {ref.expiration}, leg {self.params.leg}'s expiration, has no eligible contract"


@EXPIRATION_SELECTORS.register(
    "next_after_leg", params=NextAfterLegParams, version="1",
    description="Chooses the first eligible expiration strictly after the referenced leg's expiration, among "
                "expirations that pass the filter.")
class NextAfterLeg:
    """The ``next_after_leg`` expiration selector (SPEC-13).

    :param params: Its validated parameters.
    """

    def __init__(self, params: NextAfterLegParams) -> None:
        self.params = params

    def choose(self, options: list[ExpirationInfo], ctx: ExpirationContext) -> tuple[ExpirationInfo | None, str]:
        """Choose among eligible expirations that passed the filter.

        :param options: The expirations, ordered by expiry, then root.
        :param ctx: The selection context.
        :returns: The expiration, or None and why.
        """
        ref = ctx.selected[self.params.leg]
        for o in options:
            if o.expiry_timestamp > ref.expiry_timestamp:
                return o, ""
        return None, f"no eligible expiration after leg {self.params.leg}'s {ref.root} {ref.expiration}"


# --- strike selectors (SPEC-20 to SPEC-25) --------------------------------------------------------


def usual_spacing(listed: np.ndarray, target: float) -> float:
    """The usual strike spacing around a target: the most common gap between adjacent listed strikes near it.

    The default tolerance of ``forward`` and ``strike_offset`` (plan §7.5, answer 6). The ten listed
    strikes nearest the target are used; of equally common gaps, the smallest wins.

    :param listed: Every strike listed in the expiration, ascending.
    :param target: The target strike.
    :returns: The spacing in index points; infinity when fewer than two strikes are listed.
    """
    strikes = np.unique(listed)
    if len(strikes) < 2:
        return float("inf")
    near = np.sort(strikes[np.argsort(np.abs(strikes - target), kind="stable")[:_SPACING_STRIKES]])
    gaps = Counter(round(float(g), _ROUND) for g in np.diff(near) if g > 0)
    top = max(gaps.values())
    return min(g for g, n in gaps.items() if n == top)


def _pick(distance: np.ndarray, tolerance: float, on_no_match: OnNoMatch, order: np.ndarray, what: str) -> StrikePick:
    """Pick the candidate nearest a target, applying the tolerance and ``on_no_match``.

    :param distance: Distance of each candidate from the target (NaN when it cannot be measured).
    :param tolerance: Largest distance that matches.
    :param on_no_match: What to do when nothing is within tolerance.
    :param order: Candidate indexes in tie-break order: of equal distances, the first listed wins.
    :param what: How to name the target in messages, for example ``delta 0.30``.
    :returns: The pick.
    """
    usable = [i for i in order if not np.isnan(distance[i])]
    if not usable:
        return StrikePick(None, f"no eligible contract has a value to compare with {what}")
    rounded = np.round(distance, _ROUND)
    best = min(usable, key=lambda i: rounded[i])  # min keeps the first of equal values: the tie-break order
    if rounded[best] <= tolerance + _EPS:
        return StrikePick(int(best))
    note = f"the nearest is {rounded[best]:g} from {what}, beyond the tolerance of {tolerance:g}"
    if on_no_match is OnNoMatch.NEAREST_ANY:
        return StrikePick(int(best), note + "; took it anyway (on_no_match: nearest_any)")
    return StrikePick(None, note)


def _strike_order(c: StrikeCandidates, further_otm_first: bool) -> np.ndarray:
    """Candidate indexes in tie-break order for delta selectors.

    :param c: The candidates (ascending strikes).
    :param further_otm_first: Whether further out-of-the-money strikes win ties.
    :returns: Indexes: higher strikes first for further-OTM calls and nearer-OTM puts, otherwise lower first.
    """
    ascending = np.arange(len(c.strikes))
    higher_first = (c.option_type == "call") == further_otm_first
    return ascending[::-1] if higher_first else ascending


def _delta_pick(c: StrikeCandidates, target: float, tolerance: float, tie_break: StrikeTieBreak,
                on_no_match: OnNoMatch) -> StrikePick:
    """Pick by absolute delta (SPEC-20, SPEC-21, SPEC-27).

    :param c: The candidates.
    :param target: Target absolute delta.
    :param tolerance: Tolerance in absolute delta.
    :param tie_break: ``further_otm`` or ``nearer_otm``.
    :param on_no_match: What to do when nothing is within tolerance.
    :returns: The pick.
    """
    distance = np.abs(np.abs(c.deltas) - target)  # NaN for null deltas: never chosen (SPEC-27)
    order = _strike_order(c, tie_break is StrikeTieBreak.FURTHER_OTM)
    return _pick(distance, tolerance, on_no_match, order, f"delta {target:g}")


def _point_pick(c: StrikeCandidates, target: float, tolerance: float | None, on_no_match: OnNoMatch,
                what: str) -> StrikePick:
    """Pick the strike nearest a target strike, ties to the lower strike.

    :param c: The candidates.
    :param target: The target strike.
    :param tolerance: Tolerance in index points; None means the usual spacing around the target.
    :param on_no_match: What to do when nothing is within tolerance.
    :param what: How to name the target in messages.
    :returns: The pick.
    """
    if np.isnan(target):
        return StrikePick(None, f"{what} is not available (null)")
    tol = usual_spacing(c.listed_strikes, target) if tolerance is None else tolerance
    return _pick(np.abs(c.strikes - target), tol, on_no_match, np.arange(len(c.strikes)), what)


@STRIKE_SELECTORS.register(
    "delta", params=DeltaParams, version="1",
    description="Chooses the strike in the leg's expiration whose absolute delta (the snapshot's, CONV-10) is "
                "nearest target, within tolerance (default 0.05). Targets are absolute: 0.25 is a 25-delta call or "
                "put (CONV-4). Contracts with a null delta are not eligible (SPEC-27).")
class Delta:
    """The ``delta`` strike selector (SPEC-20).

    :param params: Its validated parameters.
    """

    def __init__(self, params: DeltaParams) -> None:
        self.params = params

    def choose(self, candidates: StrikeCandidates) -> StrikePick:
        """Choose among the expiration's eligible contracts.

        :param candidates: The candidates.
        :returns: The pick.
        """
        p = self.params
        return _delta_pick(candidates, p.target, p.tolerance, p.tie_break, p.on_no_match)


@STRIKE_SELECTORS.register(
    "atm", params=AtmParams, version="1",
    description="Chooses the at-the-money strike: the 50-delta option of the leg's own type (CONV-5), as delta "
                "with target 0.50. The strike nearest the forward is the separate forward selector.")
class Atm:
    """The ``atm`` strike selector (SPEC-21).

    :param params: Its validated parameters.
    """

    def __init__(self, params: AtmParams) -> None:
        self.params = params

    def choose(self, candidates: StrikeCandidates) -> StrikePick:
        """Choose among the expiration's eligible contracts.

        :param candidates: The candidates.
        :returns: The pick.
        """
        p = self.params
        return _delta_pick(candidates, 0.5, p.tolerance, p.tie_break, p.on_no_match)


@STRIKE_SELECTORS.register(
    "forward", params=ForwardParams, version="1",
    description="Chooses the strike nearest the series forward (DATA-14), within tolerance_points; by default the "
                "usual strike spacing around the forward in that expiration. Ties go to the lower strike.")
class Forward:
    """The ``forward`` strike selector (SPEC-22).

    :param params: Its validated parameters.
    """

    def __init__(self, params: ForwardParams) -> None:
        self.params = params

    def choose(self, candidates: StrikeCandidates) -> StrikePick:
        """Choose among the expiration's eligible contracts.

        :param candidates: The candidates.
        :returns: The pick.
        """
        return _point_pick(candidates, candidates.forward, self.params.tolerance_points, self.params.on_no_match,
                           f"the forward {candidates.forward:g}")


@STRIKE_SELECTORS.register(
    "same_strike_as", params=SameStrikeAsParams, version="1",
    description="Uses the referenced leg's strike, which must be listed in this leg's expiration (within "
                "tolerance_points, default 0: exactly the same strike). Ties go to the lower strike.")
class SameStrikeAs:
    """The ``same_strike_as`` strike selector (SPEC-23).

    :param params: Its validated parameters.
    """

    def __init__(self, params: SameStrikeAsParams) -> None:
        self.params = params

    def choose(self, candidates: StrikeCandidates) -> StrikePick:
        """Choose among the expiration's eligible contracts.

        :param candidates: The candidates.
        :returns: The pick.
        """
        ref = candidates.selected[self.params.leg]
        return _point_pick(candidates, ref.strike, self.params.tolerance_points, self.params.on_no_match,
                           f"leg {self.params.leg}'s strike {ref.strike:g}")


@STRIKE_SELECTORS.register(
    "strike_offset", params=StrikeOffsetParams, version="1",
    description="Chooses the listed strike nearest the referenced leg's strike plus an offset in points or percent, "
                "within tolerance_points; by default the usual strike spacing around the offset strike. Ties go to "
                "the lower strike.")
class StrikeOffset:
    """The ``strike_offset`` strike selector (SPEC-24).

    :param params: Its validated parameters.
    """

    def __init__(self, params: StrikeOffsetParams) -> None:
        self.params = params

    def choose(self, candidates: StrikeCandidates) -> StrikePick:
        """Choose among the expiration's eligible contracts.

        :param candidates: The candidates.
        :returns: The pick.
        """
        p = self.params
        ref = candidates.selected[p.leg].strike
        target = ref + p.points if p.points is not None else ref * (1 + p.percent / 100)
        return _point_pick(candidates, target, p.tolerance_points, p.on_no_match,
                           f"leg {p.leg}'s strike {ref:g} offset to {target:g}")


# --- legs together (SPEC-3, SPEC-4) ----------------------------------------------------------------


def _strike_candidates(view: MarketDataView, rows: pa.Table, choice: ExpirationInfo, option_type: str,
                       selected: Mapping[str, SelectedContract]) -> tuple[StrikeCandidates, pa.Table]:
    """The eligible contracts of the chosen expiration, sorted by strike, and that expiration's listed strikes.

    :param view: The step's market data.
    :param rows: The leg's eligible rows.
    :param choice: The chosen expiration.
    :param option_type: The leg's option type.
    :param selected: Contracts already selected at this step.
    :returns: The candidates and their rows, in the same order.
    """
    def same_expiration(table: pa.Table) -> np.ndarray:
        """Mask of the rows in the chosen expiration.

        :param table: Rows.
        """
        roots = table.column("root").to_numpy(zero_copy_only=False)
        expirations = table.column("expiration").to_numpy(zero_copy_only=False)
        return (roots == choice.root) & (expirations == np.datetime64(choice.expiration, "D"))

    chosen = rows.filter(pa.array(same_expiration(rows))).sort_by([("strike", "ascending")])
    listed = view.table().filter(pa.array(same_expiration(view.table()))).column("strike").to_numpy()
    forward = chosen.column("forward").to_numpy(zero_copy_only=False).astype(float)
    return StrikeCandidates(option_type=option_type, strikes=chosen.column("strike").to_numpy().astype(float),
                            deltas=chosen.column("delta").to_numpy(zero_copy_only=False).astype(float),
                            forward=float(forward[0]) if len(forward) else float("nan"),
                            listed_strikes=np.sort(listed.astype(float)), selected=selected), chosen


def select_legs(spec: StrategySpec, view: MarketDataView, calendar: SelectionCalendar,
                legs: list[str] | None = None,
                fixed: Mapping[str, SelectedContract] | None = None) -> SelectionResult:
    """Select legs' contracts at one step, atomically and in dependency order (SPEC-3, SPEC-4).

    :param spec: The spec.
    :param view: The step's market data.
    :param calendar: The trading calendar, for the standard-monthly filter.
    :param legs: The legs to select; every leg when omitted. A leg roll selects one leg (SPEC-43).
    :param fixed: Contracts already held by other legs, which references to them use (SPEC-43).
    :returns: The selected contracts, or the first failure and no contract.
    """
    order, _ = leg_order(spec)
    wanted = set(order if legs is None else legs)
    selected: dict[str, SelectedContract] = dict(fixed or {})
    chosen: dict[str, SelectedContract] = {}
    warnings: list[SelectionIssue] = []
    for leg_id in (i for i in order if i in wanted):
        leg = spec.leg(leg_id)
        exp_name = f"expiration_selector {leg.expiration.selector}"
        rows = eligible_rows(view, leg, spec)
        options = _filtered(group_expirations(rows), leg.expiration, calendar)
        expiration_selector = EXPIRATION_SELECTORS.get(leg.expiration.selector).target(leg.expiration)
        choice, why = expiration_selector.choose(options, ExpirationContext(leg_id, selected))
        if choice is None:
            return SelectionResult({}, SelectionIssue(leg_id, exp_name, why), tuple(warnings))
        candidates, candidate_rows = _strike_candidates(view, rows, choice, str(leg.option_type), selected)
        strike_name = f"strike_selector {leg.strike.selector}"
        pick = STRIKE_SELECTORS.get(leg.strike.selector).target(leg.strike).choose(candidates)
        where = f"in {choice.root} {choice.expiration}"
        if pick.index is None:
            return SelectionResult({}, SelectionIssue(leg_id, strike_name, f"{where}: {pick.message}"), tuple(warnings))
        if pick.message:
            warnings.append(SelectionIssue(leg_id, strike_name, f"{where}: {pick.message}"))
        row = candidate_rows.slice(pick.index, 1).to_pylist()[0]
        contract = SelectedContract(leg_id=leg_id, osi_symbol=row["osi_symbol"], root=row["root"],
                                    expiration=row["expiration"], option_type=row["option_type"],
                                    strike=row["strike"], expiry_timestamp=row["expiry_timestamp"], row=row)
        selected[leg_id] = contract
        chosen[leg_id] = contract
    return SelectionResult(chosen, None, tuple(warnings))
