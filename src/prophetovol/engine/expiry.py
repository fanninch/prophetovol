"""Expiration and settlement (SPEC-50 to SPEC-55).

* **Settlement** (ENG-1 step 2, SPEC-50): a PM-settled leg held to its expiry settles at the step on
  its settlement date, at the settlement source's value against the snapshot's index level (the
  adjusted close, REF-20). It is a cash flow with no fill-model cost.
* **Forced closes** (ENG-1 step 5):
  * AM-settled legs are closed on their last trading day (SPEC-51). If that day is a skipped missing
    day, at the last step before it, the last day the contract can still be closed.
  * PM-settled legs whose settlement date is a skipped missing day are closed at the last step before it
    (SPEC-55).

The step schedule, fixed at pre-flight, says which days are skipped, so no future data is read.
"""

from __future__ import annotations

from datetime import date

from prophetovol.core.errors import ConfigurationError
from prophetovol.engine.book import Book
from prophetovol.engine.schedule import StepSchedule
from prophetovol.engine.view import MarketDataView
from prophetovol.reference.settlement import settlement_source_for

FORCED_CLOSE_AM = "forced_close_am"
"""The reason of a forced close on an AM-settled leg's last trading day (SPEC-51)."""

FORCED_CLOSE_MISSING_EXPIRY = "forced_close_missing_expiry"
"""The reason of an early close before a skipped settlement date (SPEC-55)."""


def settle_expired(book: Book, view: MarketDataView) -> list[tuple[str, str]]:
    """Settle every held PM-settled leg whose expiry is at or before the step (SPEC-50).

    :param book: The book, at the start of the step.
    :param view: The step's market data.
    :returns: The (structure, leg) pairs settled, in book order.
    :raises ConfigurationError: If a held leg's expiry has passed without a settlement step, which forced closes
        prevent.
    """
    settled = []
    for s in book.open_structures():
        for leg_id, p in list(s.legs.items()):
            c = p.contract
            if c["expiry_timestamp"] > view.as_of:
                continue
            if c["settlement_style"] != "PM" or c["settlement_date"] != view.as_of_date:
                raise ConfigurationError(f"{c['osi_symbol']} expired at {c['expiry_timestamp']} but is still held at "
                                         f"step {view.step} ({view.as_of_date}): it should have been closed earlier")
            value = settlement_source_for(c["settlement_style"]).settlement_value(c["option_type"], c["strike"],
                                                                                 view.index_level)
            book.settle(s.structure_id, leg_id, value)
            settled.append((s.structure_id, leg_id))
    return settled


def _closes_today(day: date, view: MarketDataView, schedule: StepSchedule) -> bool:
    """Whether a leg that must be closed by ``day`` is closed at this step.

    :param day: The last day it can be closed on (AM) or its settlement date if skipped (PM).
    :param view: The step's market data.
    :param schedule: The run's step schedule.
    :returns: True on that day, or at the last step before it when it is skipped.
    """
    if schedule.is_missing(day):
        before = schedule.last_step_before(day)
        return before is not None and before.day == view.as_of_date
    return day == view.as_of_date


def forced_closes(book: Book, view: MarketDataView, schedule: StepSchedule) -> list[tuple[str, str, str]]:
    """The legs that must be force-closed at this step (SPEC-51, SPEC-55).

    :param book: The book.
    :param view: The step's market data.
    :param schedule: The run's step schedule.
    :returns: (structure, leg, reason) triples, in book order.
    """
    out = []
    for s in book.open_structures():
        for leg_id, p in s.legs.items():
            c = p.contract
            if c["settlement_style"] == "AM" and _closes_today(c["last_trading_date"], view, schedule):
                out.append((s.structure_id, leg_id, FORCED_CLOSE_AM))
            elif c["settlement_style"] == "PM" and schedule.is_missing(c["settlement_date"]) and \
                    _closes_today(c["settlement_date"], view, schedule):
                out.append((s.structure_id, leg_id, FORCED_CLOSE_MISSING_EXPIRY))
    return out
