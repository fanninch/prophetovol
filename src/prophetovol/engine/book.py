"""The book: structures, their legs' positions and hedges, and their accounting (ENG-20 to ENG-43).

The step loop (plan Phase 13) drives the book through each step in ENG-1's order:

1. :meth:`Book.begin_step` with the step's view;
2. :meth:`Book.settle` for PM-settled legs at expiry (SPEC-50);
3. :meth:`Book.mark` (ENG-21);
4. :meth:`Book.retry_pending_closes`, :meth:`Book.close_leg`, :meth:`Book.open_structure` and
   :meth:`Book.open_leg` for the step's orders (ENG-40, ENG-41);
5. :meth:`Book.rebalance_hedges` after the option trades (SPEC-61, SPEC-63);
6. :meth:`Book.end_step`, which computes every position's values and P&L (ENG-30) and records the
   position and portfolio snapshots (RES-1, RES-10).

Accounting, per security per step (ENG-30): market value ``q · P · m``; a trade of ``Δq`` at ``F``
has cash flow ``−Δq · F · m − fees``; settlement pays ``q · value · m``; period P&L is
``MV_t − MV_{t−1} + CF_t``. Fees are included and also reported (ENG-31). Ids of structures and
trades are sequence numbers, so runs are reproducible (ENG-10).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from prophetovol.core.errors import ConfigurationError
from prophetovol.engine.marking import mid, quote_of, valid_quote
from prophetovol.engine.orders import CONTRACT_FIELDS, OpenLeg
from prophetovol.engine.view import MarketDataView
from prophetovol.results.records import EventType, MarkSource
from prophetovol.results.recorder import RunRecorder

HEDGE = "hedge"
"""The leg id of a structure's index hedge in snapshots and trades."""

_ZERO = 1e-12


class FillModel(Protocol):
    """A fill model implementation (``engine.fills``)."""

    def price(self, buy: bool, bid: float, ask: float) -> float:
        """The fill price of an order on a valid quote.

        :param buy: True for a buy.
        :param bid: The bid.
        :param ask: The ask.
        """


class HedgeRule(Protocol):
    """A hedge rule implementation (``engine.hedging``)."""

    def target_holding(self, option_delta: float, holding: float, units: float, multiplier: float) -> float | None:
        """The hedge holding a structure should have, or None to leave it.

        :param option_delta: ``Σ q_i · δ_i`` over the structure's open legs.
        :param holding: The current holding.
        :param units: The structure's units.
        :param multiplier: The contract multiplier.
        """


@dataclass(frozen=True)
class BookSettings:
    """The run settings the book needs (from the run configuration and the underlying).

    :param multiplier: Contract multiplier m (100 for SPX).
    :param capital: Run capital in dollars (ENG-32).
    :param fill: The fill model implementation (ENG-40).
    :param commission_per_contract: Dollars per contract per side (ENG-42).
    :param hedge_cost_bps: Basis points of traded hedge notional (ENG-42).
    :param stale_mark_warning_steps: Consecutive stale steps after which each further one warns (ENG-21).
    """

    multiplier: float
    capital: float
    fill: FillModel
    commission_per_contract: float = 0.0
    hedge_cost_bps: float = 0.0
    stale_mark_warning_steps: int = 5


@dataclass
class Position:
    """One leg's option position in one contract.

    :param structure_id: Its structure.
    :param leg_id: Its leg.
    :param contract: The contract's identity fields (:data:`~prophetovol.engine.orders.CONTRACT_FIELDS`).
    :param quantity: Signed contracts held; 0 once closed or settled.
    :param last_mark: The last valid mark, carried forward when the quote is invalid (ENG-21).
    :param last_delta: The last known delta, used for hedging when the snapshot has none.
    :param stale_steps: Consecutive steps marked stale.
    :param previous_value: Market value at the previous step (ENG-30).
    :param cumulative_pnl: P&L since the position opened.
    :param row: The contract's snapshot row at this step, or None when absent.
    :param mark_price: This step's mark.
    :param mark_source: Where this step's mark came from.
    :param cash_flow: This step's cash flows.
    :param fees: This step's fees.
    :param flags: This step's flags.
    """

    structure_id: str
    leg_id: str
    contract: dict[str, Any]
    quantity: float = 0.0
    last_mark: float | None = None
    last_delta: float | None = None
    stale_steps: int = 0
    previous_value: float = 0.0
    cumulative_pnl: float = 0.0
    # this step
    row: dict[str, Any] | None = None
    mark_price: float | None = None
    mark_source: MarkSource = MarkSource.MID
    cash_flow: float = 0.0
    fees: float = 0.0
    flags: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        """The position's id: structure, leg and contract."""
        return f"{self.structure_id}/{self.leg_id}/{self.contract['osi_symbol']}"


@dataclass
class Hedge:
    """A structure's synthetic index hedge (SPEC-62): ``quantity`` index units, priced at the index level.

    :param structure_id: Its structure.
    :param quantity: The holding h in index units, fractional (SPEC-62).
    :param previous_value: Market value at the previous step.
    :param cumulative_pnl: P&L since the structure opened.
    :param cash_flow: This step's cash flows.
    :param fees: This step's hedge costs.
    :param traded: Whether it traded at this step.
    """

    structure_id: str
    quantity: float = 0.0
    previous_value: float = 0.0
    cumulative_pnl: float = 0.0
    cash_flow: float = 0.0
    fees: float = 0.0
    traded: bool = False

    @property
    def key(self) -> str:
        """The hedge's position id."""
        return f"{self.structure_id}/{HEDGE}"


@dataclass
class Structure:
    """One instance of the spec's structure (ENG-3).

    :param structure_id: Its id, for example S3.
    :param units: Structure units N.
    :param opened_step: The step it opened at.
    :param opened_as_of: When it opened.
    :param parent_id: The structure it replaced in a structure roll, if any.
    :param legs: Open positions by leg id.
    :param finished: Positions closed or settled at this step, recorded once more.
    :param hedge: Its index hedge.
    :param status: ``open``, ``closing`` (a close waits for a valid quote) or ``closed``.
    :param closed_step: The step it finished closing at.
    :param closed_as_of: When it finished closing.
    :param cumulative_pnl: Its P&L since opening: legs, hedge and fees (SPEC-46).
    """

    structure_id: str
    units: float
    opened_step: int
    opened_as_of: datetime
    parent_id: str | None = None
    legs: dict[str, Position] = field(default_factory=dict)
    finished: list[Position] = field(default_factory=list)
    hedge: Hedge = None  # type: ignore[assignment]
    status: str = "open"
    closed_step: int | None = None
    closed_as_of: datetime | None = None
    cumulative_pnl: float = 0.0

    def __post_init__(self) -> None:
        if self.hedge is None:
            self.hedge = Hedge(self.structure_id)

    @property
    def is_open(self) -> bool:
        """Whether the structure still holds or owes anything."""
        return self.status != "closed"


class Book:
    """Every structure of a run, with its positions, hedge and accounting.

    :param settings: The run's settings.
    :param recorder: Where snapshots, trades, structures and events are recorded.
    """

    def __init__(self, settings: BookSettings, recorder: RunRecorder) -> None:
        self.settings = settings
        self.recorder = recorder
        self.structures: list[Structure] = []
        self.cumulative_pnl = 0.0
        self.pending_closes: dict[str, tuple[str, str, str, bool]] = {}  # position key → (structure, leg, reason, forced)
        self._structure_seq = 0
        self._trade_seq = 0
        self._view: MarketDataView | None = None
        self._step_flags: list[str] = []

    # --- step lifecycle -----------------------------------------------------------------------

    @property
    def view(self) -> MarketDataView:
        """The current step's view."""
        if self._view is None:
            raise ConfigurationError("the book has no current step: call begin_step first")
        return self._view

    def begin_step(self, view: MarketDataView, flags: Iterable[str] = ()) -> None:
        """Start a step: bind its view and clear the per-step values.

        :param view: The step's market data.
        :param flags: Flags for every snapshot of the step, for example ``missing_day_before``.
        """
        self._view = view
        self._step_flags = list(flags)
        for s in self.open_structures():
            s.finished = []
            s.hedge.cash_flow = s.hedge.fees = 0.0
            s.hedge.traded = False
            for p in s.legs.values():
                p.row = view.contract(p.contract["osi_symbol"])
                p.cash_flow = p.fees = 0.0
                p.flags = []

    def open_structures(self) -> list[Structure]:
        """The structures not yet closed, in opening order.

        :returns: The structures.
        """
        return [s for s in self.structures if s.is_open]

    def structure(self, structure_id: str) -> Structure:
        """A structure by id.

        :param structure_id: The structure.
        :returns: It.
        :raises KeyError: If there is none.
        """
        for s in self.structures:
            if s.structure_id == structure_id:
                return s
        raise KeyError(structure_id)

    def _event(self, type: EventType, message: str, *, level: str = "info", structure_id: str | None = None,
               **details: Any) -> None:
        """Record an event at the current step.

        :param type: What happened.
        :param message: For people.
        :param level: ``info`` or ``warning``.
        :param structure_id: The structure concerned.
        :param details: Structured details.
        """
        self.recorder.event(self.view.step, self.view.as_of, type, message, level=level, structure_id=structure_id,
                            **details)

    # --- marking (ENG-21, ENG-22) ---------------------------------------------------------------

    def mark(self) -> None:
        """Mark every open position at the mid of its valid quote, or carry its last valid mark (ENG-21).

        A stale step is flagged ``stale_mark`` with an event; beyond ``stale_mark_warning_steps`` consecutive
        stale steps, the event is a warning.
        """
        for s in self.open_structures():
            for p in s.legs.values():
                bid, ask = quote_of(p.row)
                if valid_quote(bid, ask):
                    p.mark_price, p.mark_source, p.last_mark, p.stale_steps = mid(bid, ask), MarkSource.MID, mid(bid, ask), 0
                    if p.row.get("delta") is not None:
                        p.last_delta = p.row["delta"]
                    continue
                p.stale_steps += 1
                p.mark_price, p.mark_source = p.last_mark, MarkSource.STALE
                p.flags.append("stale_mark")
                warn = p.stale_steps > self.settings.stale_mark_warning_steps
                why = "is missing from the snapshot" if p.row is None else f"has an invalid quote ({bid}/{ask})"
                self._event(EventType.STALE_MARK,
                            f"{p.contract['osi_symbol']} {why}; marked at its last valid mark {p.last_mark:g}"
                            f" ({p.stale_steps} consecutive stale step{'s' if p.stale_steps != 1 else ''})",
                            level="warning" if warn else "info", structure_id=s.structure_id, leg_id=p.leg_id,
                            osi_symbol=p.contract["osi_symbol"], stale_steps=p.stale_steps)

    # --- trading (ENG-40 to ENG-43) --------------------------------------------------------------

    def _trade(self, structure_id: str, leg_id: str, key: str, osi_symbol: str | None, action: str, quantity: float,
               price: float, fees: float, multiplier: float, reason: str, forced: bool) -> float:
        """Record a trade and return its cash flow ``−Δq · F · m − fees``.

        :param structure_id: The structure.
        :param leg_id: The leg, or hedge.
        :param key: The position's id.
        :param osi_symbol: The contract, or None for the hedge.
        :param action: ``open``, ``close`` or ``adjust``.
        :param quantity: Signed quantity traded.
        :param price: Price per unit.
        :param fees: Fees paid.
        :param multiplier: m, or 1 for the hedge.
        :param reason: Why.
        :param forced: Whether it is a forced close.
        :returns: The cash flow.
        """
        self._trade_seq += 1
        cash = -quantity * price * multiplier - fees
        self.recorder.add("trades", trade_id=f"T{self._trade_seq}", step=self.view.step, as_of=self.view.as_of,
                          structure_id=structure_id, leg_id=leg_id, position_key=key, osi_symbol=osi_symbol,
                          action=action, quantity=quantity, price=price, fees=fees, cash_flow=cash, reason=reason,
                          forced=forced)
        return cash

    def _commission(self, quantity: float) -> float:
        """Commission on a number of contracts, one side (ENG-42).

        :param quantity: Signed contracts.
        :returns: Dollars.
        """
        return abs(quantity) * self.settings.commission_per_contract

    def open_structure(self, legs: list[OpenLeg], units: float, reason: str = "entry",
                       parent_id: str | None = None) -> Structure | None:
        """Open a new structure, all legs or none (ENG-41).

        :param legs: One opening order per leg, in the spec's leg order.
        :param units: Structure units N.
        :param reason: Why it opens: ``entry`` or ``roll``.
        :param parent_id: The structure it replaces in a structure roll.
        :returns: The structure, or None when a leg's quote is invalid: then nothing is traded and an
            ``order_not_filled`` event names the legs.
        """
        quotes = {o.leg_id: quote_of(self.view.contract(o.osi_symbol)) for o in legs}
        invalid = [o for o in legs if not valid_quote(*quotes[o.leg_id])]
        if invalid:
            self._event(EventType.ORDER_NOT_FILLED,
                        "opening order dropped: no valid quote for "
                        + ", ".join(f"{o.leg_id} ({o.osi_symbol})" for o in invalid),
                        level="warning", reason=reason, legs=[o.leg_id for o in invalid])
            return None
        self._structure_seq += 1
        s = Structure(f"S{self._structure_seq}", units, self.view.step, self.view.as_of, parent_id)
        self.structures.append(s)
        for o in legs:
            self._fill_open(s, o, quotes[o.leg_id], reason)
        self._record_structure(s)
        return s

    def open_leg(self, structure_id: str, leg: OpenLeg, reason: str) -> bool:
        """Open one leg in an existing structure: the opening side of a leg roll (SPEC-43).

        :param structure_id: The structure.
        :param leg: The opening order.
        :param reason: Why, for example ``roll``.
        :returns: Whether it filled; if not, the leg stays closed and an ``order_not_filled`` event says so.
        """
        s = self.structure(structure_id)
        bid, ask = quote_of(self.view.contract(leg.osi_symbol))
        if not valid_quote(bid, ask):
            self._event(EventType.ORDER_NOT_FILLED, f"opening order dropped: no valid quote for {leg.leg_id} "
                                                    f"({leg.osi_symbol})", level="warning",
                        structure_id=structure_id, reason=reason, legs=[leg.leg_id])
            return False
        self._fill_open(s, leg, (bid, ask), reason)
        return True

    def _fill_open(self, s: Structure, order: OpenLeg, quote: tuple[float, float], reason: str) -> None:
        """Fill an opening order on a valid quote and mark the new position at the mid (ENG-43).

        :param s: The structure.
        :param order: The order.
        :param quote: Its valid bid and ask.
        :param reason: Why.
        """
        if order.leg_id in s.legs:
            raise ConfigurationError(f"{s.structure_id} already holds leg {order.leg_id}")
        bid, ask = quote
        price = self.settings.fill.price(order.quantity > 0, bid, ask)
        fees = self._commission(order.quantity)
        row = self.view.contract(order.osi_symbol)
        p = Position(s.structure_id, order.leg_id, {k: order.contract.get(k) for k in CONTRACT_FIELDS},
                     quantity=order.quantity, last_mark=mid(bid, ask), last_delta=row.get("delta"), row=row,
                     mark_price=mid(bid, ask), mark_source=MarkSource.MID)
        p.cash_flow += self._trade(s.structure_id, order.leg_id, p.key, order.osi_symbol, "open", order.quantity, price,
                                   fees, self.settings.multiplier, reason, False)
        p.fees += fees
        s.legs[order.leg_id] = p

    def close_leg(self, structure_id: str, leg_id: str, reason: str, forced: bool = False) -> bool:
        """Close a leg's position (ENG-41, SPEC-51, SPEC-55).

        On a valid quote it fills through the fill model. Otherwise an ordinary close waits and is retried at
        the next step (:meth:`retry_pending_closes`) while the position keeps its stale mark; a forced close is
        never retried and closes at the last valid mark with no fill-model cost, commission still paid,
        flagged ``forced_close_stale``.

        :param structure_id: The structure.
        :param leg_id: The leg.
        :param reason: Why, for example a trigger's name or ``forced_close_am``.
        :param forced: Whether it is a forced close.
        :returns: Whether the position is now closed.
        """
        s = self.structure(structure_id)
        p = s.legs.get(leg_id)
        if p is None:
            return True
        bid, ask = quote_of(p.row)
        q = p.quantity
        if valid_quote(bid, ask):
            price = self.settings.fill.price(-q > 0, bid, ask)
            p.mark_source = MarkSource.FILL
        elif forced:
            price = p.last_mark
            p.mark_source = MarkSource.STALE
            p.flags.append("forced_close_stale")
            self._event(EventType.ORDER_NOT_FILLED,
                        f"forced close of {p.contract['osi_symbol']} without a valid quote: closed at its last valid "
                        f"mark {price:g}", level="warning", structure_id=structure_id, leg_id=leg_id, reason=reason)
        else:
            if p.key not in self.pending_closes:
                self._event(EventType.ORDER_NOT_FILLED,
                            f"close of {p.contract['osi_symbol']} not filled: no valid quote; retried next step",
                            level="warning", structure_id=structure_id, leg_id=leg_id, reason=reason)
            self.pending_closes[p.key] = (structure_id, leg_id, reason, False)
            return False
        fees = self._commission(q)
        p.cash_flow += self._trade(structure_id, leg_id, p.key, p.contract["osi_symbol"], "close", -q, price, fees,
                                   self.settings.multiplier, reason, forced)
        p.fees += fees
        p.mark_price = price
        p.quantity = 0.0
        self.pending_closes.pop(p.key, None)
        s.finished.append(s.legs.pop(leg_id))
        return True

    def retry_pending_closes(self) -> None:
        """Retry closes that could not fill at an earlier step (ENG-41), in the order they were asked for."""
        for key, (structure_id, leg_id, reason, forced) in list(self.pending_closes.items()):
            if self.close_leg(structure_id, leg_id, reason, forced):
                self._event(EventType.CLOSE, f"pending close of {key} filled", structure_id=structure_id,
                            leg_id=leg_id, reason=reason)

    def settle(self, structure_id: str, leg_id: str, value: float) -> None:
        """Settle a leg at expiry for a per-unit value (SPEC-50): a cash flow ``q · value · m`` with no fill cost.

        :param structure_id: The structure.
        :param leg_id: The leg.
        :param value: The settlement value per unit, for example the intrinsic value.
        """
        s = self.structure(structure_id)
        p = s.legs.pop(leg_id)
        cash = p.quantity * value * self.settings.multiplier
        p.cash_flow += cash
        self._event(EventType.SETTLEMENT, f"{p.contract['osi_symbol']} settled at {value:g}: "
                                          f"{p.quantity:g} contracts, ${cash:,.2f}",
                    structure_id=structure_id, leg_id=leg_id, value=value, quantity=p.quantity, cash_flow=cash)
        p.quantity, p.mark_price, p.mark_source = 0.0, value, MarkSource.SETTLEMENT
        self.pending_closes.pop(p.key, None)
        s.finished.append(p)

    # --- hedging (SPEC-60 to SPEC-64) --------------------------------------------------------------

    def option_delta(self, s: Structure) -> float:
        """``Σ q_i · δ_i`` over a structure's open legs, with each leg's latest known delta.

        :param s: The structure.
        :returns: Signed contracts times delta.
        """
        total = 0.0
        for p in s.legs.values():
            delta = p.row.get("delta") if p.row is not None and p.row.get("delta") is not None else p.last_delta
            total += p.quantity * (delta or 0.0)
        return total

    def rebalance_hedges(self, rule: HedgeRule) -> None:
        """Trade each open structure's hedge as its rule says, after the step's option trades (SPEC-61, SPEC-63).

        A structure with no open leg closes its hedge (SPEC-64). Hedge trades are at the step's index level, with
        the hedge cost in basis points of traded notional (ENG-25, ENG-42).

        :param rule: The spec's hedge rule implementation.
        """
        level = self.view.index_level
        for s in self.open_structures():
            h = s.hedge
            target = 0.0 if not s.legs else rule.target_holding(self.option_delta(s), h.quantity, s.units,
                                                               self.settings.multiplier)
            if target is None or abs(target - h.quantity) <= _ZERO:
                continue
            change = target - h.quantity
            fees = self.settings.hedge_cost_bps / 10_000 * abs(change) * level
            h.cash_flow += self._trade(s.structure_id, HEDGE, h.key, None, "adjust", change, level, fees, 1.0, "hedge",
                                       False)
            h.fees += fees
            h.quantity, h.traded = target, True
            self._event(EventType.HEDGE_TRADE, f"{s.structure_id} hedge {change:+.6g} index units at {level:g} "
                                               f"(holding {target:.6g})",
                        structure_id=s.structure_id, quantity=change, price=level, holding=target)

    # --- accounting and recording (ENG-30 to ENG-32, RES-1, RES-10) --------------------------------

    def end_step(self) -> None:
        """Value every position touched at the step, update P&L, and record the snapshots (ENG-30, RES-1, RES-10)."""
        view, m = self.view, self.settings.multiplier
        totals = dict.fromkeys(("market_value", "cash_flow", "fees", "period_pnl", "dollar_delta",
                                "dollar_gamma_1pct", "dollar_vega", "dollar_theta"), 0.0)
        contracts_held = 0.0
        for s in self.open_structures():
            structure_period = 0.0
            for p in [*s.finished, *s.legs.values()]:
                row = self._position_row(p, view, m)
                structure_period += row["period_pnl"]
                contracts_held += abs(p.quantity)
                self._add(totals, row)
            h = s.hedge
            if h.quantity != 0 or h.traded or h.previous_value != 0:
                row = self._hedge_row(h, view)
                structure_period += row["period_pnl"]
                self._add(totals, row)
            s.cumulative_pnl += structure_period
            pending = any(v[0] == s.structure_id for v in self.pending_closes.values())
            if not s.legs and abs(h.quantity) <= _ZERO and not pending:
                s.status, s.closed_step, s.closed_as_of = "closed", view.step, view.as_of
            else:
                s.status = "closing" if pending else "open"
            self._record_structure(s)
        self.cumulative_pnl += totals["period_pnl"]
        self.recorder.add("portfolio_snapshots", step=view.step, as_of=view.as_of, index_level=view.index_level,
                          market_value=totals["market_value"], cash_flow=totals["cash_flow"], fees=totals["fees"],
                          period_pnl=totals["period_pnl"], cumulative_pnl=self.cumulative_pnl,
                          equity=self.settings.capital + self.cumulative_pnl,
                          period_return=totals["period_pnl"] / self.settings.capital,
                          dollar_delta=totals["dollar_delta"], dollar_gamma_1pct=totals["dollar_gamma_1pct"],
                          dollar_vega=totals["dollar_vega"], dollar_theta=totals["dollar_theta"],
                          open_structures=len(self.open_structures()), contracts_held=contracts_held,
                          worst_stress_loss=None, flags=list(self._step_flags))

    @staticmethod
    def _add(totals: dict[str, float], row: dict[str, Any]) -> None:
        """Add a position snapshot's values to the step totals (null greeks count as 0).

        :param totals: The running totals.
        :param row: The snapshot row.
        """
        for k in totals:
            totals[k] += row[k] or 0.0

    def _position_row(self, p: Position, view: MarketDataView, m: float) -> dict[str, Any]:
        """Value an option position, update its P&L, and record its snapshot.

        :param p: The position.
        :param view: The step's view.
        :param m: The multiplier.
        :returns: The recorded row.
        """
        row = p.row or {}
        value = p.quantity * (p.mark_price or 0.0) * m
        period = value - p.previous_value + p.cash_flow
        p.cumulative_pnl += period
        p.previous_value = value
        greeks = {g: row.get(g) for g in ("delta", "gamma", "vega", "theta")}
        s, q = view.index_level, p.quantity
        flags = [*p.flags, *self._step_flags] + (["vendor_flagged"] if row.get("vendor_flag") else [])
        record = dict(
            step=view.step, as_of=view.as_of, structure_id=p.structure_id, leg_id=p.leg_id, position_key=p.key,
            **p.contract, quantity=q,
            time_to_expiry_years=row.get("time_to_expiry_years"), days_to_expiry=row.get("days_to_expiry"),
            trading_days_to_expiry=row.get("trading_days_to_expiry"),
            mark=p.mark_price, mark_source=p.mark_source.value, bid=row.get("bid"), ask=row.get("ask"),
            iv=row.get("iv"), index_level=s, forward=row.get("forward"), forward_source=row.get("forward_source"),
            market_value=value, cash_flow=p.cash_flow, fees=p.fees, period_pnl=period,
            cumulative_pnl=p.cumulative_pnl, **greeks,
            dollar_delta=None if greeks["delta"] is None else greeks["delta"] * q * m * s,
            dollar_gamma_1pct=None if greeks["gamma"] is None else greeks["gamma"] * q * m * s * s * 0.01,
            dollar_vega=None if greeks["vega"] is None else greeks["vega"] * q * m,
            dollar_theta=None if greeks["theta"] is None else greeks["theta"] * q * m,
            flags=flags)
        self.recorder.add("position_snapshots", **record)
        return record

    def _hedge_row(self, h: Hedge, view: MarketDataView) -> dict[str, Any]:
        """Value a structure's hedge, update its P&L, and record its snapshot (RES-2).

        :param h: The hedge.
        :param view: The step's view.
        :returns: The recorded row.
        """
        s = view.index_level
        value = h.quantity * s
        period = value - h.previous_value + h.cash_flow
        h.cumulative_pnl += period
        h.previous_value = value
        record = dict(
            step=view.step, as_of=view.as_of, structure_id=h.structure_id, leg_id=HEDGE, position_key=h.key,
            **dict.fromkeys(CONTRACT_FIELDS), quantity=h.quantity, time_to_expiry_years=None, days_to_expiry=None,
            trading_days_to_expiry=None, mark=s, mark_source=MarkSource.INDEX.value, bid=None, ask=None, iv=None,
            index_level=s, forward=None, forward_source=None, market_value=value, cash_flow=h.cash_flow, fees=h.fees,
            period_pnl=period, cumulative_pnl=h.cumulative_pnl, delta=1.0, gamma=0.0, vega=0.0, theta=0.0,
            dollar_delta=h.quantity * s, dollar_gamma_1pct=0.0, dollar_vega=0.0, dollar_theta=0.0,
            flags=list(self._step_flags))
        self.recorder.add("position_snapshots", **record)
        return record

    def _record_structure(self, s: Structure) -> None:
        """Record a structure's current state.

        :param s: The structure.
        """
        self.recorder.set_structure(s.structure_id, parent_id=s.parent_id, units=s.units, opened_step=s.opened_step,
                                    opened_as_of=s.opened_as_of, closed_step=s.closed_step,
                                    closed_as_of=s.closed_as_of, status=s.status, cumulative_pnl=s.cumulative_pnl)
