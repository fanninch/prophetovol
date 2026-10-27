"""Trigger conditions and actions (SPEC-40 to SPEC-46).

At each step, after marking, every open structure's triggers are evaluated on that step's marks and
the snapshot's greeks (SPEC-42). A trigger fires when any of its conditions does; a condition that
needs a null greek is false and is reported (SPEC-42). Of the triggers that fire, one action is
chosen per structure: structure close, then structure roll, then leg close, then leg roll, in the
triggers' listed order within each (SPEC-44). Every time quantity comes from timestamps and the
calendar, never from step counts (ENG-4).

The implementations are registered here with their parameter models (decision 29).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from prophetovol.pricing.time import time_to_expiry_years
from prophetovol.registry.catalog import TRIGGER_ACTIONS, TRIGGER_CONDITIONS
from prophetovol.registry.params.triggers import (CloseParams, DayUnit, LegAbsDeltaAboveParams, LegAbsDeltaBelowParams,
                                                  LegDaysToExpiryAtOrBelowParams, RollParams,
                                                  StructureMinDaysToExpiryAtOrBelowParams,
                                                  StructurePnlPerUnitAtOrAboveParams,
                                                  StructurePnlPerUnitAtOrBelowParams, TradingDaysHeldAtLeastParams)
from prophetovol.strategy.model import StrategySpec, Trigger

_EPS = 1e-9


class TriggerCalendar(Protocol):
    """The calendar lookup conditions need (``reference.calendar.TradingCalendar`` has it)."""

    def sessions_after_through(self, start: date, end: date) -> int:
        """Count trading days ``d`` with ``start < d <= end``.

        :param start: Exclusive lower bound.
        :param end: Inclusive upper bound.
        """


@dataclass(frozen=True)
class LegState:
    """What conditions read about one held leg at a step.

    :param leg_id: The leg.
    :param row: The contract's snapshot row at the step, or None when absent.
    :param expiry_timestamp: The contract's expiry instant (UTC).
    :param settlement_date: Its settlement date.
    """

    leg_id: str
    row: dict[str, Any] | None
    expiry_timestamp: datetime
    settlement_date: date


@dataclass(frozen=True)
class ConditionContext:
    """What a condition may read at a step (REG-4: the structure's own state and the calendar).

    :param as_of: The step's as-of instant (UTC).
    :param as_of_date: The step's trading day.
    :param legs: The structure's held legs by id.
    :param pnl_per_unit: The structure's cumulative P&L per unit at the step's marks, in dollars (SPEC-46).
    :param opened_day: The day the structure opened.
    :param calendar: The trading calendar.
    :param timezone: The exchange's IANA time zone, for exchange-clock time to expiry (CONV-1).
    """

    as_of: datetime
    as_of_date: date
    legs: dict[str, LegState]
    pnl_per_unit: float
    opened_day: date
    calendar: TriggerCalendar
    timezone: str

    def days_to_expiry(self, leg: LegState, unit: DayUnit) -> float:
        """A held leg's time to expiry in a unit (CONV-1, CONV-2), from its row or, when absent, from its expiry.

        :param leg: The leg.
        :param unit: ``calendar_days`` (fractional) or ``trading_days``.
        :returns: The time to expiry.
        """
        if unit is DayUnit.TRADING_DAYS:
            if leg.row is not None and leg.row.get("trading_days_to_expiry") is not None:
                return float(leg.row["trading_days_to_expiry"])
            return float(self.calendar.sessions_after_through(self.as_of_date, leg.settlement_date))
        if leg.row is not None and leg.row.get("days_to_expiry") is not None:
            return float(leg.row["days_to_expiry"])
        zone = ZoneInfo(self.timezone)
        local = lambda instant: instant.astimezone(zone).replace(tzinfo=None)  # noqa: E731 - exchange clock time
        return time_to_expiry_years(local(self.as_of), local(leg.expiry_timestamp)) * 365


@dataclass(frozen=True)
class ConditionResult:
    """A condition's outcome at a step.

    :param fired: Whether it fires.
    :param value: The measured value, for the event.
    :param null_greek: The greek that was null, when it could not be evaluated (SPEC-42).
    """

    fired: bool
    value: float | None = None
    null_greek: str | None = None


def _delta_condition(ctx: ConditionContext, leg_id: str, test: Callable[[float], bool]) -> ConditionResult:
    """Evaluate a test on a leg's absolute delta.

    :param ctx: The context.
    :param leg_id: The leg.
    :param test: The comparison.
    :returns: The result; false when the leg is not held, or with ``null_greek`` when its delta is null.
    """
    leg = ctx.legs.get(leg_id)
    if leg is None:
        return ConditionResult(False)
    delta = None if leg.row is None else leg.row.get("delta")
    if delta is None:
        return ConditionResult(False, null_greek="delta")
    return ConditionResult(test(abs(delta)), abs(delta))


@TRIGGER_CONDITIONS.register(
    "leg_abs_delta_above", params=LegAbsDeltaAboveParams, version="1",
    description="Fires when the absolute delta of the leg's contract (the snapshot's, CONV-10) is above threshold. "
                "A null delta evaluates to false with a warning event (SPEC-42).")
class LegAbsDeltaAbove:
    """The ``leg_abs_delta_above`` condition.

    :param params: Its validated parameters.
    """

    def __init__(self, params: LegAbsDeltaAboveParams) -> None:
        self.params = params

    def evaluate(self, ctx: ConditionContext) -> ConditionResult:
        """Evaluate at a step.

        :param ctx: The structure's state at the step.
        :returns: The result.
        """
        return _delta_condition(ctx, self.params.leg, lambda d: d > self.params.threshold + _EPS)


@TRIGGER_CONDITIONS.register(
    "leg_abs_delta_below", params=LegAbsDeltaBelowParams, version="1",
    description="Fires when the absolute delta of the leg's contract is below threshold. A null delta evaluates to "
                "false with a warning event (SPEC-42).")
class LegAbsDeltaBelow:
    """The ``leg_abs_delta_below`` condition.

    :param params: Its validated parameters.
    """

    def __init__(self, params: LegAbsDeltaBelowParams) -> None:
        self.params = params

    def evaluate(self, ctx: ConditionContext) -> ConditionResult:
        """Evaluate at a step.

        :param ctx: The structure's state at the step.
        :returns: The result.
        """
        return _delta_condition(ctx, self.params.leg, lambda d: d < self.params.threshold - _EPS)


@TRIGGER_CONDITIONS.register(
    "leg_days_to_expiry_at_or_below", params=LegDaysToExpiryAtOrBelowParams, version="1",
    description="Fires when the leg's time to expiry is at or below days, measured in unit: calendar_days "
                "(fractional, CONV-1) or trading_days (CONV-2).")
class LegDaysToExpiryAtOrBelow:
    """The ``leg_days_to_expiry_at_or_below`` condition.

    :param params: Its validated parameters.
    """

    def __init__(self, params: LegDaysToExpiryAtOrBelowParams) -> None:
        self.params = params

    def evaluate(self, ctx: ConditionContext) -> ConditionResult:
        """Evaluate at a step.

        :param ctx: The structure's state at the step.
        :returns: The result; false when the leg is not held.
        """
        leg = ctx.legs.get(self.params.leg)
        if leg is None:
            return ConditionResult(False)
        days = ctx.days_to_expiry(leg, self.params.unit)
        return ConditionResult(days <= self.params.days + _EPS, days)


@TRIGGER_CONDITIONS.register(
    "structure_min_days_to_expiry_at_or_below", params=StructureMinDaysToExpiryAtOrBelowParams, version="1",
    description="Fires when the shortest time to expiry among the structure's open legs is at or below days, "
                "measured in unit.")
class StructureMinDaysToExpiryAtOrBelow:
    """The ``structure_min_days_to_expiry_at_or_below`` condition.

    :param params: Its validated parameters.
    """

    def __init__(self, params: StructureMinDaysToExpiryAtOrBelowParams) -> None:
        self.params = params

    def evaluate(self, ctx: ConditionContext) -> ConditionResult:
        """Evaluate at a step.

        :param ctx: The structure's state at the step.
        :returns: The result; false with no leg held.
        """
        if not ctx.legs:
            return ConditionResult(False)
        days = min(ctx.days_to_expiry(leg, self.params.unit) for leg in ctx.legs.values())
        return ConditionResult(days <= self.params.days + _EPS, days)


@TRIGGER_CONDITIONS.register(
    "structure_pnl_per_unit_at_or_above", params=StructurePnlPerUnitAtOrAboveParams, version="1",
    description="A profit target: fires when the structure's cumulative P&L since it opened (legs, hedge and fees), "
                "divided by its units, is at or above amount dollars (SPEC-46).")
class StructurePnlPerUnitAtOrAbove:
    """The ``structure_pnl_per_unit_at_or_above`` condition.

    :param params: Its validated parameters.
    """

    def __init__(self, params: StructurePnlPerUnitAtOrAboveParams) -> None:
        self.params = params

    def evaluate(self, ctx: ConditionContext) -> ConditionResult:
        """Evaluate at a step.

        :param ctx: The structure's state at the step.
        :returns: The result.
        """
        return ConditionResult(ctx.pnl_per_unit >= self.params.amount - _EPS, ctx.pnl_per_unit)


@TRIGGER_CONDITIONS.register(
    "structure_pnl_per_unit_at_or_below", params=StructurePnlPerUnitAtOrBelowParams, version="1",
    description="A stop: fires when the structure's cumulative P&L since it opened (legs, hedge and fees), divided "
                "by its units, is at or below amount dollars, a zero or negative number (SPEC-46).")
class StructurePnlPerUnitAtOrBelow:
    """The ``structure_pnl_per_unit_at_or_below`` condition.

    :param params: Its validated parameters.
    """

    def __init__(self, params: StructurePnlPerUnitAtOrBelowParams) -> None:
        self.params = params

    def evaluate(self, ctx: ConditionContext) -> ConditionResult:
        """Evaluate at a step.

        :param ctx: The structure's state at the step.
        :returns: The result.
        """
        return ConditionResult(ctx.pnl_per_unit <= self.params.amount + _EPS, ctx.pnl_per_unit)


@TRIGGER_CONDITIONS.register(
    "trading_days_held_at_least", params=TradingDaysHeldAtLeastParams, version="1",
    description="Fires when the structure has been held at least days trading days, counted on the trading calendar.")
class TradingDaysHeldAtLeast:
    """The ``trading_days_held_at_least`` condition.

    :param params: Its validated parameters.
    """

    def __init__(self, params: TradingDaysHeldAtLeastParams) -> None:
        self.params = params

    def evaluate(self, ctx: ConditionContext) -> ConditionResult:
        """Evaluate at a step.

        :param ctx: The structure's state at the step.
        :returns: The result.
        """
        held = ctx.calendar.sessions_after_through(ctx.opened_day, ctx.as_of_date)
        return ConditionResult(held >= self.params.days, float(held))


@TRIGGER_ACTIONS.register(
    "close", params=CloseParams, version="1",
    description="With leg scope, closes that leg and keeps the structure open with its remaining legs. With "
                "structure scope, closes every leg and the structure's hedge.")
class Close:
    """The ``close`` action (SPEC-43).

    :param params: Its validated parameters (none).
    """

    def __init__(self, params: CloseParams | None = None) -> None:
        self.params = params or CloseParams()


@TRIGGER_ACTIONS.register(
    "roll", params=RollParams, version="1",
    description="With leg scope, closes the leg and re-selects it with its original selectors, keeping its quantity. "
                "With structure scope, closes the structure and opens a new one with the spec's selectors and "
                "sizing, recording the old one as its parent (CONV-9). The opening side waits until the closing side "
                "fills.")
class Roll:
    """The ``roll`` action (SPEC-43).

    :param params: Its validated parameters (none).
    """

    def __init__(self, params: RollParams | None = None) -> None:
        self.params = params or RollParams()


# --- choosing one action per structure (SPEC-44) -------------------------------------------------

_PRECEDENCE = {("structure", "close"): 0, ("structure", "roll"): 1, ("leg", "close"): 2, ("leg", "roll"): 3}


@dataclass(frozen=True)
class FiredTrigger:
    """A trigger that fired, with the conditions that fired it.

    :param name: The trigger's name.
    :param action: ``close`` or ``roll``.
    :param leg_id: The leg it acts on, or None for the structure.
    :param conditions: The conditions that fired, each with its name and measured value.
    """

    name: str
    action: str
    leg_id: str | None
    conditions: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class TriggerDecision:
    """The action chosen for a structure at a step, and every trigger that fired (SPEC-44).

    :param chosen: The trigger whose action is taken.
    :param fired: Every trigger that fired, in the spec's order.
    """

    chosen: FiredTrigger
    fired: tuple[FiredTrigger, ...]


@dataclass
class Evaluation:
    """The outcome of evaluating a structure's triggers at a step.

    :param decision: The action to take, or None when nothing fired.
    :param null_greeks: Conditions that needed a null greek, as (trigger, condition, greek) (SPEC-42).
    """

    decision: TriggerDecision | None = None
    null_greeks: list[tuple[str, str, str]] = field(default_factory=list)


def evaluate_triggers(spec: StrategySpec, ctx: ConditionContext) -> Evaluation:
    """Evaluate a structure's triggers and choose one action (SPEC-41 to SPEC-44).

    :param spec: The spec.
    :param ctx: The structure's state at the step.
    :returns: The chosen action, if any, and the conditions that met a null greek.
    """
    out = Evaluation()
    fired: list[FiredTrigger] = []
    for trigger in spec.triggers:
        hits: list[dict[str, Any]] = []
        for cond in trigger.any_of:
            result = TRIGGER_CONDITIONS.get(cond.condition).target(cond).evaluate(ctx)
            if result.null_greek:
                out.null_greeks.append((trigger.name, cond.condition, result.null_greek))
            if result.fired:
                hits.append({"condition": cond.condition, "value": result.value})
        if hits and _acts_on_held_leg(trigger, ctx):
            fired.append(FiredTrigger(trigger.name, trigger.action, trigger.scope.leg, tuple(hits)))
    if fired:
        chosen = min(fired, key=lambda f: _PRECEDENCE[("leg" if f.leg_id else "structure", f.action)])
        out.decision = TriggerDecision(chosen, tuple(fired))
    return out


def _acts_on_held_leg(trigger: Trigger, ctx: ConditionContext) -> bool:
    """Whether a trigger's scope is something the structure holds now.

    :param trigger: The trigger.
    :param ctx: The structure's state.
    :returns: False for a leg-scoped trigger whose leg is not held.
    """
    return trigger.scope.leg is None or trigger.scope.leg in ctx.legs
