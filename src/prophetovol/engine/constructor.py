"""The constructor: what a step's orders are, and why (ENG-2, ENG-1 steps 4 to 6).

The ``rules`` constructor applies a :class:`~prophetovol.strategy.model.StrategySpec`:

* **step 4:** each open structure's triggers, one action each (SPEC-40 to SPEC-46);
* **step 5:** forced closes (SPEC-51, SPEC-55), then ``expiry_handling`` for structures with a leg
  settled or force-closed at the step (SPEC-54);
* **step 6:** the opening sides of rolls and the entry schedule, selected (SPEC-3, SPEC-4) and sized
  (SPEC-70 to SPEC-73) at the step's view.

A roll's opening side waits until its closing side has filled (plan §7.5, answer 1): the closes
execute first, and a roll whose close is still pending opens at the step its close fills. A failed
selection skips the entry, or leaves a rolled leg or structure closed (SPEC-45), with an event.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from prophetovol.engine.book import Book, Position, Structure
from prophetovol.engine.entries import EntryState
from prophetovol.engine.expiry import forced_closes
from prophetovol.engine.gate import OpeningOrder
from prophetovol.engine.orders import OpenLeg
from prophetovol.engine.schedule import StepSchedule
from prophetovol.engine.selection import SelectedContract, SelectionResult, select_legs
from prophetovol.engine.sizing import round_units
from prophetovol.engine.triggers import ConditionContext, LegState, evaluate_triggers
from prophetovol.engine.view import MarketDataView
from prophetovol.registry.catalog import CONSTRUCTORS, ENTRY_SCHEDULES, SIZING_METHODS
from prophetovol.registry.params.fills import RulesParams
from prophetovol.results.records import EventType
from prophetovol.strategy.model import ExpiryHandling, Side, StrategySpec


@dataclass(frozen=True)
class CloseRequest:
    """A leg to close at the step.

    :param structure_id: The structure.
    :param leg_id: The leg.
    :param reason: Why: a trigger's name, ``expiry_handling``, ``roll``, or a forced close's reason.
    :param forced: Whether it is a forced close (never retried, ENG-41).
    """

    structure_id: str
    leg_id: str
    reason: str
    forced: bool = False


@dataclass(frozen=True)
class RollRequest:
    """A roll whose opening side opens once its closing side has filled (SPEC-43, plan §7.5 answer 1).

    :param structure_id: The structure rolled, or whose leg is rolled.
    :param leg_id: The leg rolled; None for a structure roll.
    :param reason: The trigger's name, or ``expiry_handling`` for ``roll_leg`` (SPEC-54).
    """

    structure_id: str
    leg_id: str | None
    reason: str


@dataclass
class StepPlan:
    """What steps 4 and 5 decided: the closes to execute and the rolls to open.

    :param closes: Legs to close, in book and leg order.
    :param rolls: Rolls decided at this step.
    :param closing_by_action: Structures being closed by a close action or expiry handling, for ``when_flat``'s
        cooldown (SPEC-31).
    """

    closes: list[CloseRequest] = field(default_factory=list)
    rolls: list[RollRequest] = field(default_factory=list)
    closing_by_action: set[str] = field(default_factory=set)


@CONSTRUCTORS.register(
    "rules", params=RulesParams, version="1",
    description="Applies a StrategySpec: evaluates its triggers, the forced closes and expiry handling, and its entry "
                "schedule at each step, and returns orders with their reasons (ENG-1 steps 4 to 6).")
class Rules:
    """The ``rules`` constructor (ENG-2): a strategy spec's rules, step by step.

    :param params: Its validated parameters (none).
    :param spec: The spec it applies.
    :param schedule: The run's step schedule.
    :param calendar: The trading calendar.
    :param timezone: The exchange's IANA time zone (CONV-1).
    :param rounding: The run's rounding of structure units (SPEC-72).
    """

    def __init__(self, params: RulesParams | None = None, *, spec: StrategySpec | None = None,
                 schedule: StepSchedule | None = None, calendar: object = None, timezone: str = "America/New_York",
                 rounding: str = "whole") -> None:
        self.params = params or RulesParams()
        self.spec = spec
        self.schedule = schedule
        self.calendar = calendar
        self.timezone = timezone
        self.rounding = rounding
        self.pending_rolls: list[RollRequest] = []
        self.opened_any = False
        self.last_close_day: date | None = None
        self._closing_by_action: set[str] = set()
        if spec is not None:
            self._entry = ENTRY_SCHEDULES.get(spec.entry.schedule).target(spec.entry)
            self._sizing = SIZING_METHODS.get(spec.sizing.method).target(spec.sizing)

    # --- steps 4 and 5 ---------------------------------------------------------------------------

    def plan(self, book: Book, view: MarketDataView, settled: list[tuple[str, str]]) -> StepPlan:
        """Decide the step's closes and rolls: triggers, forced closes and expiry handling (ENG-1 steps 4, 5).

        :param book: The book, settled and marked.
        :param view: The step's market data.
        :param settled: The (structure, leg) pairs settled at step 2.
        :returns: The plan.
        """
        plan = StepPlan()
        busy = {r.structure_id for r in self.pending_rolls} | {v[0] for v in book.pending_closes.values()}
        closing: dict[tuple[str, str], CloseRequest] = {}
        rolled_structures: set[str] = set()
        for s in book.open_structures():
            if s.structure_id in busy or not s.legs:
                continue
            ctx = self._context(book, s, view)
            evaluation = evaluate_triggers(self.spec, ctx)
            for trigger, condition, greek in evaluation.null_greeks:
                book.recorder.event(view.step, view.as_of, EventType.CONDITION_NULL_GREEK,
                                    f"{trigger}: {condition} needs {greek}, which is null; evaluated as false",
                                    level="warning", structure_id=s.structure_id, trigger=trigger,
                                    condition=condition, greek=greek)
            decision = evaluation.decision
            if decision is None:
                continue
            chosen = decision.chosen
            book.recorder.event(view.step, view.as_of, EventType.TRIGGER_FIRED,
                                f"{chosen.name}: {chosen.action} {chosen.leg_id or 'structure'}",
                                structure_id=s.structure_id, chosen=chosen.name, action=chosen.action,
                                leg=chosen.leg_id,
                                fired=[{"trigger": f.name, "action": f.action, "leg": f.leg_id,
                                        "conditions": list(f.conditions)} for f in decision.fired])
            legs = list(s.legs) if chosen.leg_id is None else [chosen.leg_id]
            for leg_id in legs:
                closing[(s.structure_id, leg_id)] = CloseRequest(s.structure_id, leg_id, chosen.name)
            if chosen.action == "roll":
                plan.rolls.append(RollRequest(s.structure_id, chosen.leg_id, chosen.name))
                if chosen.leg_id is None:
                    rolled_structures.add(s.structure_id)
            elif chosen.leg_id is None or len(s.legs) == 1:
                plan.closing_by_action.add(s.structure_id)

        expired: dict[str, list[str]] = {}
        for structure_id, leg_id in settled:
            expired.setdefault(structure_id, []).append(leg_id)
        for structure_id, leg_id, reason in forced_closes(book, view, self.schedule):
            closing[(structure_id, leg_id)] = CloseRequest(structure_id, leg_id, reason, forced=True)
            expired.setdefault(structure_id, []).append(leg_id)
            book.recorder.event(view.step, view.as_of, EventType(reason),
                                f"{leg_id} must close at this step ({reason})", structure_id=structure_id, leg=leg_id)
        for structure_id, legs in expired.items():
            if structure_id in rolled_structures:
                continue
            s = book.structure(structure_id)
            handling = self.spec.expiry_handling
            if handling is ExpiryHandling.CLOSE_STRUCTURE:
                for leg_id in s.legs:
                    closing.setdefault((structure_id, leg_id), CloseRequest(structure_id, leg_id, "expiry_handling"))
                plan.closing_by_action.add(structure_id)
            elif handling is ExpiryHandling.ROLL_LEG:
                plan.rolls.extend(RollRequest(structure_id, leg_id, "expiry_handling") for leg_id in legs)
            elif not [i for i in s.legs if (structure_id, i) not in closing]:
                plan.closing_by_action.add(structure_id)  # keep_remaining with nothing left: closed by expiry

        order = {s.structure_id: n for n, s in enumerate(book.structures)}
        legs_order = {leg.id: n for n, leg in enumerate(self.spec.legs)}
        plan.closes = sorted(closing.values(), key=lambda c: (order[c.structure_id], legs_order.get(c.leg_id, 0)))
        self._closing_by_action |= plan.closing_by_action
        return plan

    def _context(self, book: Book, s: Structure, view: MarketDataView) -> ConditionContext:
        """The state conditions read for a structure at the step.

        :param book: The book.
        :param s: The structure.
        :param view: The step's market data.
        :returns: The context.
        """
        legs = {leg_id: LegState(leg_id, p.row, p.contract["expiry_timestamp"], p.contract["settlement_date"])
                for leg_id, p in s.legs.items()}
        return ConditionContext(as_of=view.as_of, as_of_date=view.as_of_date, legs=legs,
                                pnl_per_unit=book.pnl_now(s) / s.units,
                                opened_day=self.schedule.steps[s.opened_step - 1].day, calendar=self.calendar,
                                timezone=self.timezone)

    def execute_closes(self, book: Book, plan: StepPlan) -> None:
        """Execute the step's closes, ordinary or forced (ENG-41).

        :param book: The book.
        :param plan: The step's plan.
        """
        for c in plan.closes:
            filled = book.close_leg(c.structure_id, c.leg_id, c.reason, c.forced)
            if filled and not c.forced:
                book.recorder.event(book.view.step, book.view.as_of, EventType.CLOSE,
                                    f"closed {c.leg_id} ({c.reason})", structure_id=c.structure_id, leg=c.leg_id,
                                    reason=c.reason)
        self.pending_rolls.extend(plan.rolls)

    # --- step 6 ------------------------------------------------------------------------------------

    def openings(self, book: Book, view: MarketDataView) -> list[OpeningOrder]:
        """Build the step's opening orders: rolls whose closes have filled, then the entry (ENG-1 step 6).

        :param book: The book after the step's closes.
        :param view: The step's market data.
        :returns: Sized opening orders, for the gate.
        """
        orders: list[OpeningOrder] = []
        waiting: list[RollRequest] = []
        for roll in self.pending_rolls:
            s = book.structure(roll.structure_id)
            pending = any(v[0] == roll.structure_id and (roll.leg_id is None or v[1] == roll.leg_id)
                          for v in book.pending_closes.values())
            ready = not pending and (roll.leg_id not in s.legs if roll.leg_id else not s.legs)
            if not ready:
                waiting.append(roll)
                continue
            order = self._leg_roll(book, s, roll, view) if roll.leg_id else self._structure_roll(s, roll, view, book)
            if order is not None:
                orders.append(order)
        self.pending_rolls = waiting
        entry = self._entry_order(book, view, sum(o.kind == "roll_structure" for o in orders))
        if entry is not None:
            orders.append(entry)
        return orders

    def _quantities(self, units: float, result: SelectionResult) -> list[OpenLeg]:
        """Opening orders for selected legs: N · ratio contracts, signed by side (SPEC-70).

        :param units: Structure units N.
        :param result: The selection.
        :returns: One order per leg, in the spec's leg order.
        """
        out = []
        for leg in self.spec.legs:
            if leg.id in result.contracts:
                sign = 1.0 if leg.side is Side.LONG else -1.0
                out.append(OpenLeg(leg.id, result.contracts[leg.id].row, sign * units * leg.ratio))
        return out

    def _selection_failed(self, book: Book, view: MarketDataView, result: SelectionResult, what: str,
                          structure_id: str | None = None) -> None:
        """Record a failed selection (SPEC-4, SPEC-45).

        :param book: The book.
        :param view: The step's market data.
        :param result: The failed selection.
        :param what: What was being opened, for the message.
        :param structure_id: The structure concerned, if any.
        """
        f = result.failure
        book.recorder.event(view.step, view.as_of, EventType.SELECTION_FAILED,
                            f"{what}: leg {f.leg_id} could not be selected ({f.selector}): {f.message}",
                            level="warning", structure_id=structure_id, leg=f.leg_id, selector=f.selector,
                            reason=f.message)

    def _units(self, book: Book, view: MarketDataView, what: str, structure_id: str | None = None) -> float | None:
        """Size an opening (SPEC-70 to SPEC-72), recording a skip when it rounds below one unit.

        :param book: The book.
        :param view: The step's market data.
        :param what: What is being opened, for the message.
        :param structure_id: The structure concerned, if any.
        :returns: Units, or None when the opening is skipped.
        """
        raw = self._sizing.units(view.index_level, book.settings.multiplier)
        units = round_units(raw, self.rounding)
        if units is None:
            book.recorder.event(view.step, view.as_of, EventType.ENTRY_SKIPPED,
                                f"{what} skipped: {raw:.4g} units round down to zero (whole rounding)",
                                level="warning", structure_id=structure_id, units=raw)
        return units

    def _leg_roll(self, book: Book, s: Structure, roll: RollRequest, view: MarketDataView) -> OpeningOrder | None:
        """The opening side of a leg roll: the leg re-selected with its selectors, its quantity kept (SPEC-43, SPEC-73).

        :param book: The book.
        :param s: The structure.
        :param roll: The roll.
        :param view: The step's market data.
        :returns: The order, or None when selection failed (the leg stays closed, SPEC-45).
        """
        fixed = {leg_id: _held(p) for leg_id, p in s.legs.items()}
        result = select_legs(self.spec, view, self.calendar, legs=[roll.leg_id], fixed=fixed)
        if not result.ok:
            self._selection_failed(book, view, result, f"roll of {s.structure_id} leg {roll.leg_id}", s.structure_id)
            return None
        return OpeningOrder("roll_leg", self._quantities(s.units, result), s.units, roll.reason,
                            structure_id=s.structure_id, warnings=[w.message for w in result.warnings])

    def _structure_roll(self, s: Structure, roll: RollRequest, view: MarketDataView,
                        book: Book) -> OpeningOrder | None:
        """The opening side of a structure roll: a new structure, re-selected and re-sized (CONV-9, SPEC-73).

        :param s: The structure rolled.
        :param roll: The roll.
        :param view: The step's market data.
        :param book: The book.
        :returns: The order, or None when selection or sizing failed (the structure stays closed, SPEC-45).
        """
        result = select_legs(self.spec, view, self.calendar)
        if not result.ok:
            self._selection_failed(book, view, result, f"roll of {s.structure_id}", s.structure_id)
            return None
        units = self._units(book, view, f"roll of {s.structure_id}", s.structure_id)
        if units is None:
            return None
        return OpeningOrder("roll_structure", self._quantities(units, result), units, roll.reason,
                            parent_id=s.structure_id, warnings=[w.message for w in result.warnings])

    def _entry_order(self, book: Book, view: MarketDataView, opening_rolls: int) -> OpeningOrder | None:
        """The entry, when the schedule says one is due (SPEC-30 to SPEC-35).

        :param book: The book after the step's closes.
        :param view: The step's market data.
        :param opening_rolls: Structures the step's rolls are about to open.
        :returns: The order, or None.
        """
        open_now = sum(1 for s in book.open_structures()
                       if s.legs or any(v[0] == s.structure_id for v in book.pending_closes.values()))
        state = EntryState(day=view.as_of_date, first_day=self.schedule.steps[0].day,
                           open_structures=open_now + opening_rolls, opened_any=self.opened_any,
                           last_close_day=self.last_close_day)
        if not self._entry.due(state, self.calendar):
            return None
        result = select_legs(self.spec, view, self.calendar)
        if not result.ok:
            self._selection_failed(book, view, result, "entry")
            return None
        units = self._units(book, view, "entry")
        if units is None:
            return None
        return OpeningOrder("entry", self._quantities(units, result), units, "entry",
                            warnings=[w.message for w in result.warnings])

    # --- step 8 ------------------------------------------------------------------------------------

    def execute_openings(self, book: Book, orders: list[OpeningOrder]) -> None:
        """Open what the gate passed (ENG-1 step 8), recording entries and rolls (RES-20).

        :param book: The book.
        :param orders: The gate's orders.
        """
        view = book.view
        for o in orders:
            legs = ", ".join(f"{leg.leg_id} {leg.osi_symbol} × {leg.quantity:g}" for leg in o.legs)
            level = "warning" if o.warnings else "info"
            if o.kind == "roll_leg":
                if book.open_leg(o.structure_id, o.legs[0], o.reason):
                    book.recorder.event(view.step, view.as_of, EventType.ROLL, f"rolled {legs} ({o.reason})",
                                        level=level, structure_id=o.structure_id, legs=legs, warnings=o.warnings)
                continue
            s = book.open_structure(o.legs, o.units, "entry" if o.kind == "entry" else "roll", o.parent_id)
            if s is None:
                continue
            if o.kind == "entry":
                self.opened_any = True
                book.recorder.event(view.step, view.as_of, EventType.ENTRY,
                                    f"opened {s.structure_id}, {o.units:g} unit(s): {legs}", level=level,
                                    structure_id=s.structure_id, units=o.units, legs=legs, warnings=o.warnings)
            else:
                book.recorder.event(view.step, view.as_of, EventType.ROLL,
                                    f"rolled {o.parent_id} into {s.structure_id}, {o.units:g} unit(s): {legs} "
                                    f"({o.reason})", level=level, structure_id=s.structure_id, parent=o.parent_id,
                                    units=o.units, legs=legs, warnings=o.warnings)

    def after_step(self, book: Book, view: MarketDataView) -> None:
        """Note structures closed at the step by a close action or by expiry, for ``when_flat``'s cooldown (SPEC-31).

        :param book: The book after the step.
        :param view: The step's market data.
        """
        for s in book.structures:
            if s.closed_step == view.step and s.structure_id in self._closing_by_action:
                self.last_close_day = view.as_of_date
        self._closing_by_action = {i for i in self._closing_by_action if book.structure(i).is_open}


def _held(p: Position) -> SelectedContract:
    """A held position as a selected contract, for references from a rolled leg (SPEC-43).

    :param p: The position.
    :returns: The contract it holds, with its latest snapshot row.
    """
    row = p.row or dict(p.contract)
    c = p.contract
    return SelectedContract(leg_id=p.leg_id, osi_symbol=c["osi_symbol"], root=c["root"], expiration=c["expiration"],
                            option_type=c["option_type"], strike=c["strike"], expiry_timestamp=c["expiry_timestamp"],
                            row=row)
