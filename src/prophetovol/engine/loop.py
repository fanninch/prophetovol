"""The engine: a run's steps, each in ENG-1's order (ENG-1 to ENG-4, ARC-2).

:func:`run_engine` is a pure function of its inputs: the spec, the settings, the step schedule, one
market view per step, the calendar and a recorder (plan §4.7). It reads no file, database, network
or clock and uses no randomness (ENG-10). At each step:

1. open the view (the provider hands over one per step, ARC-3);
2. settle PM-settled legs at expiry (SPEC-50);
3. mark every position (ENG-21);
4. evaluate triggers, one action per structure (SPEC-40 to SPEC-46);
5. add forced closes and apply ``expiry_handling`` (SPEC-51 to SPEC-55);
6. build the opening orders of rolls and entries, selected and sized (SPEC-3, SPEC-30 to SPEC-35,
   SPEC-70 to SPEC-73);
7. pass them through the order gate (M2: pass-through; M3: stress);
8. execute, then rebalance the hedges (ENG-40, SPEC-61);
9. record the snapshots and events (RES-1, RES-10, RES-20).

Within step 8, pending and new closes execute before the openings are built (steps 6 and 7), so a
roll opens only once its close has filled, and the gate sees the book after the closes. At the end
the accounting invariants are checked (ENG-33); a violation fails the run.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from prophetovol.core.errors import ConfigurationError
from prophetovol.engine.book import Book, BookSettings
from prophetovol.engine.constructor import Rules
from prophetovol.engine.expiry import settle_expired
from prophetovol.engine.gate import OrderGate, PassThroughGate
from prophetovol.engine.invariants import check_invariants
from prophetovol.engine.schedule import StepSchedule
from prophetovol.engine.view import MarketDataView
from prophetovol.registry.catalog import HEDGE_RULES, load_builtins
from prophetovol.results.recorder import RunRecorder
from prophetovol.strategy.model import StrategySpec


@dataclass(frozen=True)
class EngineSettings:
    """What the engine needs besides the spec: the book's settings and the run's conventions.

    :param book: Multiplier, capital, fill model, costs and stale-mark warnings.
    :param rounding: ``whole`` or ``fractional`` structure units (SPEC-72).
    :param timezone: The exchange's IANA time zone, for exchange-clock time to expiry (CONV-1).
    """

    book: BookSettings
    rounding: str = "whole"
    timezone: str = "America/New_York"


@dataclass(frozen=True)
class RunOutcome:
    """How the engine finished.

    :param status: ``completed``, or ``cancelled`` at a step boundary (RUN-22).
    :param steps_completed: Steps fully processed and recorded.
    :param last_as_of: The as-of instant of the last step processed, if any.
    """

    status: Literal["completed", "cancelled"]
    steps_completed: int
    last_as_of: datetime | None


def run_engine(spec: StrategySpec, settings: EngineSettings, schedule: StepSchedule,
               views: Iterable[MarketDataView], calendar: object, recorder: RunRecorder,
               gate: OrderGate | None = None, progress: Callable[[int, int, datetime], None] | None = None,
               cancelled: Callable[[], bool] | None = None) -> RunOutcome:
    """Run a spec through every step of its schedule (ENG-1).

    :param spec: The validated spec.
    :param settings: The engine settings.
    :param schedule: The step schedule fixed by pre-flight.
    :param views: One view per step, in step order (from the market data provider).
    :param calendar: The trading calendar.
    :param recorder: Where the run's output is collected (RUN-23).
    :param gate: The order gate; pass-through when omitted (decision 32).
    :param progress: Called after each step with steps done, steps in total and the step's as-of time (RUN-21).
    :param cancelled: Checked after each step; when it returns True the run stops there (RUN-22).
    :returns: How the run finished; its output is in ``recorder`` whatever happened.
    :raises InvariantViolation: If the accounting does not reconcile (ENG-33).
    :raises ConfigurationError: If the views do not follow the schedule.
    """
    load_builtins()  # every implementation the spec may name is registered
    book = Book(settings.book, recorder)
    rules = Rules(spec=spec, schedule=schedule, calendar=calendar, timezone=settings.timezone,
                  rounding=settings.rounding)
    hedge_rule = HEDGE_RULES.get(spec.hedge.rule).target(spec.hedge)
    gate = gate or PassThroughGate()
    total, done, last = len(schedule.steps), 0, None
    status: Literal["completed", "cancelled"] = "completed"
    for step, view in zip(schedule.steps, views):
        if view.step != step.seq or view.as_of != step.as_of:
            raise ConfigurationError(f"view for step {view.step} ({view.as_of}) does not match step {step.seq} "
                                     f"({step.as_of})")
        book.begin_step(view, ["missing_day_before"] if step.after_missing_days else [])  # 1
        settled = settle_expired(book, view)                                               # 2
        book.mark()                                                                        # 3
        plan = rules.plan(book, view, settled)                                             # 4, 5
        book.retry_pending_closes()                                                        # 8: closes first
        rules.execute_closes(book, plan)
        orders = gate.review(rules.openings(book, view), book, view)                       # 6, 7
        rules.execute_openings(book, orders)                                               # 8
        book.rebalance_hedges(hedge_rule)
        book.end_step()                                                                    # 9
        rules.after_step(book, view)
        done, last = done + 1, view.as_of
        if progress is not None:
            progress(done, total, view.as_of)
        if cancelled is not None and cancelled() and done < total:
            status = "cancelled"
            break
    check_invariants(recorder)
    return RunOutcome(status, done, last)
