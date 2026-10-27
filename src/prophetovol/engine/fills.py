"""Fill models (ENG-40 to ENG-43).

A fill model prices an order on a valid quote (ENG-20): each implementation's :meth:`price` takes
the side and the quote. Orders on invalid quotes are handled by the book (ENG-41): opening orders
are dropped, closing orders retried, forced closes taken at the last valid mark.
"""

from __future__ import annotations

from pydantic import BaseModel

from prophetovol.registry.catalog import FILL_MODELS
from prophetovol.registry.params.fills import CrossSpreadParams, MidParams, MidPlusFractionParams


@FILL_MODELS.register("mid", params=MidParams, version="1", description="Fills at the mid of the valid quote.")
class Mid:
    """The ``mid`` fill model.

    :param params: Its validated parameters.
    """

    def __init__(self, params: MidParams) -> None:
        self.params = params

    def price(self, buy: bool, bid: float, ask: float) -> float:
        """The fill price: the mid.

        :param buy: True for a buy, False for a sell.
        :param bid: A valid bid.
        :param ask: A valid ask.
        :returns: ``(bid + ask) / 2``.
        """
        return (bid + ask) / 2


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

    def price(self, buy: bool, bid: float, ask: float) -> float:
        """The fill price: the ask for a buy, the bid for a sell.

        :param buy: True for a buy, False for a sell.
        :param bid: A valid bid.
        :param ask: A valid ask.
        :returns: The price.
        """
        return ask if buy else bid


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

    def price(self, buy: bool, bid: float, ask: float) -> float:
        """The fill price: the mid moved ``fraction`` of the half-spread against the trader.

        :param buy: True for a buy, False for a sell.
        :param bid: A valid bid.
        :param ask: A valid ask.
        :returns: ``mid ± fraction · (ask − bid) / 2``.
        """
        half = self.params.fraction * (ask - bid) / 2
        return (bid + ask) / 2 + (half if buy else -half)


def fill_model(params: BaseModel) -> Mid | CrossSpread | MidPlusFraction:
    """The fill model implementation for its registry parameters.

    :param params: A fill model's parameter model, with its ``fill_model`` name.
    :returns: The implementation.
    """
    return FILL_MODELS.get(params.fill_model).target(params)
