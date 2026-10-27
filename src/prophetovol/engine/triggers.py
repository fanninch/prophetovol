"""Trigger conditions and actions (SPEC-40 to SPEC-46).

Phase 9 registers every condition and action with its parameter model, so specs validate
(decision 29); each implementation holds its validated parameters. The behavior arrives in plan
Phase 13.
"""

from __future__ import annotations

from prophetovol.registry.catalog import TRIGGER_ACTIONS, TRIGGER_CONDITIONS
from prophetovol.registry.params.triggers import (CloseParams, LegAbsDeltaAboveParams, LegAbsDeltaBelowParams,
                                                  LegDaysToExpiryAtOrBelowParams, RollParams,
                                                  StructureMinDaysToExpiryAtOrBelowParams,
                                                  StructurePnlPerUnitAtOrAboveParams,
                                                  StructurePnlPerUnitAtOrBelowParams, TradingDaysHeldAtLeastParams)


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


@TRIGGER_CONDITIONS.register(
    "trading_days_held_at_least", params=TradingDaysHeldAtLeastParams, version="1",
    description="Fires when the structure has been held at least days trading days, counted on the trading calendar.")
class TradingDaysHeldAtLeast:
    """The ``trading_days_held_at_least`` condition.

    :param params: Its validated parameters.
    """

    def __init__(self, params: TradingDaysHeldAtLeastParams) -> None:
        self.params = params


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
