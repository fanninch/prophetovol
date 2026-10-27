"""Constructors: the component that turns a step's state into orders (ENG-2).

Phase 9 registers the ``rules`` constructor (decision 29); its behavior arrives in plan Phase 13.
"""

from __future__ import annotations

from prophetovol.registry.catalog import CONSTRUCTORS
from prophetovol.registry.params.fills import RulesParams


@CONSTRUCTORS.register(
    "rules", params=RulesParams, version="1",
    description="Applies a StrategySpec: evaluates its triggers, the forced closes and expiry handling, and its entry "
                "schedule at each step, and returns orders with their reasons (ENG-1 steps 4 to 6).")
class Rules:
    """The ``rules`` constructor (ENG-2).

    :param params: Its validated parameters (none).
    """

    def __init__(self, params: RulesParams | None = None) -> None:
        self.params = params or RulesParams()
