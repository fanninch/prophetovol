"""Hedge rules (SPEC-60 to SPEC-64).

Phase 9 registers every rule with its parameter model, so specs validate (decision 29); each
implementation holds its validated parameters. The hedging behavior arrives in plan Phase 12.
"""

from __future__ import annotations

from prophetovol.registry.catalog import HEDGE_RULES
from prophetovol.registry.params.hedge import BandParams, NoHedgeParams


@HEDGE_RULES.register("none", params=NoHedgeParams, version="1", description="No hedging.")
class NoHedge:
    """The ``none`` hedge rule (SPEC-60).

    :param params: Its validated parameters.
    """

    def __init__(self, params: NoHedgeParams) -> None:
        self.params = params


@HEDGE_RULES.register(
    "band", params=BandParams, version="1",
    description="Keeps the structure's net delta per unit within [lower, upper]: after the step's option trades, if "
                "it is outside the band, the hedge is traded so it equals target. The hedge is a synthetic index "
                "position, fractional and never rounded, traded at the index level with the run's hedge cost "
                "(SPEC-62), and closed with its structure.")
class Band:
    """The ``band`` hedge rule (SPEC-61).

    :param params: Its validated parameters.
    """

    def __init__(self, params: BandParams) -> None:
        self.params = params
