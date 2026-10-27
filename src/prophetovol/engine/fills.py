"""Fill models (ENG-40 to ENG-43).

Phase 9 registers every fill model with its parameter model (decision 29); each implementation
holds its validated parameters. The fill behavior arrives in plan Phase 12.
"""

from __future__ import annotations

from prophetovol.registry.catalog import FILL_MODELS
from prophetovol.registry.params.fills import CrossSpreadParams, MidParams, MidPlusFractionParams


@FILL_MODELS.register("mid", params=MidParams, version="1", description="Fills at the mid of the valid quote.")
class Mid:
    """The ``mid`` fill model.

    :param params: Its validated parameters.
    """

    def __init__(self, params: MidParams) -> None:
        self.params = params


@FILL_MODELS.register(
    "cross_spread", params=CrossSpreadParams, version="1",
    description="Buys at the ask and sells at the bid. The default fill model; trades at a price worse than the mid "
                "show as a first-step loss against the mid mark (ENG-43).")
class CrossSpread:
    """The ``cross_spread`` fill model.

    :param params: Its validated parameters.
    """

    def __init__(self, params: CrossSpreadParams) -> None:
        self.params = params


@FILL_MODELS.register(
    "mid_plus_fraction", params=MidPlusFractionParams, version="1",
    description="Fills at the mid plus fraction of the half-spread against the trader: fraction 0 is the mid, "
                "1 crosses the spread.")
class MidPlusFraction:
    """The ``mid_plus_fraction`` fill model.

    :param params: Its validated parameters.
    """

    def __init__(self, params: MidPlusFractionParams) -> None:
        self.params = params
