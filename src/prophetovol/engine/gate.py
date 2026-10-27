"""The stress gate at ENG-1 step 7 (decision 32).

Opening orders (entries and the opening sides of rolls) are sized first, then reviewed by an
:class:`OrderGate`, which may pass, reduce or skip them; closing orders are never gated (STR-31).
M2 ships :class:`PassThroughGate`; M3 replaces it with the stress modes without changing the loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from prophetovol.engine.book import Book
from prophetovol.engine.orders import OpenLeg
from prophetovol.engine.view import MarketDataView


@dataclass(frozen=True)
class OpeningOrder:
    """An opening the step will execute: a new structure, or the opening side of a roll.

    :param kind: ``entry``, ``roll_structure`` or ``roll_leg``.
    :param legs: The legs to open, with their contracts and signed quantities.
    :param units: Structure units N (for a leg roll, the structure's units).
    :param reason: Why: ``entry``, or the roll's trigger name or ``expiry_handling``.
    :param structure_id: For a leg roll, the structure the leg reopens in.
    :param parent_id: For a structure roll, the structure it replaces.
    :param warnings: Selection warnings to record with it, for example a ``nearest_any`` pick.
    """

    kind: str
    legs: list[OpenLeg]
    units: float
    reason: str
    structure_id: str | None = None
    parent_id: str | None = None
    warnings: list[str] = field(default_factory=list)


class OrderGate(Protocol):
    """Reviews a step's opening orders before they execute (ENG-1 step 7)."""

    def review(self, orders: list[OpeningOrder], book: Book, view: MarketDataView) -> list[OpeningOrder]:
        """Return the orders to execute, possibly reduced or fewer.

        :param orders: The step's sized opening orders.
        :param book: The book after the step's closes.
        :param view: The step's market data.
        """


class PassThroughGate:
    """The M2 gate: every opening order passes unchanged (decision 32)."""

    def review(self, orders: list[OpeningOrder], book: Book, view: MarketDataView) -> list[OpeningOrder]:
        """Pass every order.

        :param orders: The step's sized opening orders.
        :param book: The book after the step's closes.
        :param view: The step's market data.
        :returns: The orders, unchanged.
        """
        return orders
