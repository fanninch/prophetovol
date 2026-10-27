"""Parameter models of the trigger conditions and actions (SPEC-40 to SPEC-46).

Each condition model carries its ``condition`` name as a literal, so a trigger's ``any_of`` list
holds a discriminated union of these models. The behavior is in :mod:`prophetovol.engine.triggers`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DayUnit(StrEnum):
    """The unit a days-to-expiry condition measures in (SPEC-41, TIME-3)."""

    CALENDAR_DAYS = "calendar_days"
    TRADING_DAYS = "trading_days"


_UNIT = ("Unit of days: calendar_days (default; fractional calendar days to expiry, CONV-1) or trading_days "
         "(CONV-2). State it explicitly: the dry run warns when it is left out.")


class LegAbsDeltaAboveParams(BaseModel):
    """``leg_abs_delta_above``: fires when the leg's absolute delta is above a threshold."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    condition: Literal["leg_abs_delta_above"] = Field(description="Selects this condition.")
    leg: str = Field(description="Id of the leg whose contract's delta is read (CONV-10).")
    threshold: float = Field(ge=0, le=1, description="Fires when |delta| > threshold, for example 0.50.")


class LegAbsDeltaBelowParams(BaseModel):
    """``leg_abs_delta_below``: fires when the leg's absolute delta is below a threshold."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    condition: Literal["leg_abs_delta_below"] = Field(description="Selects this condition.")
    leg: str = Field(description="Id of the leg whose contract's delta is read (CONV-10).")
    threshold: float = Field(ge=0, le=1, description="Fires when |delta| < threshold, for example 0.15.")


class LegDaysToExpiryAtOrBelowParams(BaseModel):
    """``leg_days_to_expiry_at_or_below``: fires when the leg's time to expiry is at or below ``days``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    condition: Literal["leg_days_to_expiry_at_or_below"] = Field(description="Selects this condition.")
    leg: str = Field(description="Id of the leg whose time to expiry is read.")
    days: float = Field(ge=0, description="Fires when the leg's time to expiry, measured in unit, is ≤ days.")
    unit: DayUnit = Field(default=DayUnit.CALENDAR_DAYS, description=_UNIT)


class StructureMinDaysToExpiryAtOrBelowParams(BaseModel):
    """``structure_min_days_to_expiry_at_or_below``: fires when the shortest time to expiry among open legs is at or below ``days``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    condition: Literal["structure_min_days_to_expiry_at_or_below"] = Field(description="Selects this condition.")
    days: float = Field(ge=0, description="Fires when the shortest time to expiry among the structure's open legs, "
                                          "measured in unit, is ≤ days.")
    unit: DayUnit = Field(default=DayUnit.CALENDAR_DAYS, description=_UNIT)


class StructurePnlPerUnitAtOrAboveParams(BaseModel):
    """``structure_pnl_per_unit_at_or_above``: a profit target in dollars per structure unit (SPEC-46)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    condition: Literal["structure_pnl_per_unit_at_or_above"] = Field(description="Selects this condition.")
    amount: float = Field(description="Dollars per unit: fires when the structure's cumulative P&L (legs, hedge and "
                                      "fees) divided by its units is ≥ amount. 250 on a 10-unit structure fires at "
                                      "$2,500.")


class StructurePnlPerUnitAtOrBelowParams(BaseModel):
    """``structure_pnl_per_unit_at_or_below``: a stop in dollars per structure unit (SPEC-46)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    condition: Literal["structure_pnl_per_unit_at_or_below"] = Field(description="Selects this condition.")
    amount: float = Field(le=0, description="Dollars per unit, zero or negative: fires when the structure's cumulative "
                                            "P&L (legs, hedge and fees) divided by its units is ≤ amount.")


class TradingDaysHeldAtLeastParams(BaseModel):
    """``trading_days_held_at_least``: fires once the structure has been held a number of trading days."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    condition: Literal["trading_days_held_at_least"] = Field(description="Selects this condition.")
    days: int = Field(ge=1, description="Trading days since the structure was opened, counted on the trading "
                                        "calendar (ENG-4); fires when ≥ days.")


TRIGGER_CONDITION_PARAMS: tuple[type[BaseModel], ...] = (
    LegAbsDeltaAboveParams, LegAbsDeltaBelowParams, LegDaysToExpiryAtOrBelowParams,
    StructureMinDaysToExpiryAtOrBelowParams, StructurePnlPerUnitAtOrAboveParams,
    StructurePnlPerUnitAtOrBelowParams, TradingDaysHeldAtLeastParams)
"""Every trigger condition's parameter model, in the order the requirements list them."""


class CloseParams(BaseModel):
    """``close`` takes no parameters: it closes the leg, or the whole structure and its hedge (SPEC-43)."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class RollParams(BaseModel):
    """``roll`` takes no parameters: it closes and re-selects the leg, or the whole structure (SPEC-43, CONV-9)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
