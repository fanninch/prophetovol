"""Hedge rules (SPEC-60 to SPEC-64).

After the step's option trades, each structure's hedge rule says what index holding ``h`` it should
have (:meth:`target_holding`). The measure is the structure's net delta per unit,

    ``(Σ q_i · δ_i + h / m) / N``

with leg quantities ``q_i`` in signed contracts, the snapshot's deltas ``δ_i``, multiplier ``m`` and
``N`` structure units (SPEC-61). The hedge is fractional and never rounded (SPEC-62).
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

    def target_holding(self, option_delta: float, holding: float, units: float, multiplier: float) -> float | None:
        """The hedge holding the structure should have now.

        :param option_delta: ``Σ q_i · δ_i`` over the structure's open legs.
        :param holding: The current hedge holding h, in index units.
        :param units: The structure's units N.
        :param multiplier: The contract multiplier m.
        :returns: None: no hedging.
        """
        return None


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

    def measure(self, option_delta: float, holding: float, units: float, multiplier: float) -> float:
        """The structure's net delta per unit (SPEC-61).

        :param option_delta: ``Σ q_i · δ_i`` over the structure's open legs.
        :param holding: The hedge holding h, in index units.
        :param units: The structure's units N.
        :param multiplier: The contract multiplier m.
        :returns: ``(Σ q_i · δ_i + h / m) / N``.
        """
        return (option_delta + holding / multiplier) / units

    def target_holding(self, option_delta: float, holding: float, units: float, multiplier: float) -> float | None:
        """The hedge holding the structure should have now.

        :param option_delta: ``Σ q_i · δ_i`` over the structure's open legs.
        :param holding: The current hedge holding h, in index units.
        :param units: The structure's units N.
        :param multiplier: The contract multiplier m.
        :returns: None when the measure is inside ``[lower, upper]`` (to 1e-9); otherwise the holding that makes
            it equal ``target``: ``m · (target · N − Σ q_i · δ_i)``.
        """
        p = self.params
        if p.lower - 1e-9 <= self.measure(option_delta, holding, units, multiplier) <= p.upper + 1e-9:
            return None
        return multiplier * (p.target * units - option_delta)
