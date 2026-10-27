"""Parameter models of the entry schedules (SPEC-30 to SPEC-35).

Each model carries its ``schedule`` name as a literal, so a spec's ``entry`` field is a
discriminated union of these models. The behavior is in :mod:`prophetovol.engine.entries`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from prophetovol.registry.params.selection import Weekday

_MAX_OPEN = ("Most structures of this spec open at once; no entry occurs while this many are open (SPEC-34). "
             "Default 1.")


class HolidayShift(StrEnum):
    """What a ``weekdays`` schedule does when a listed weekday is not a trading day (SPEC-33)."""

    NEXT = "next"
    SKIP = "skip"


class OnceParams(BaseModel):
    """``once``: open one structure at the first step of the run (SPEC-30)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schedule: Literal["once"] = Field(description="Selects this entry schedule.")


class WhenFlatParams(BaseModel):
    """``when_flat``: open a structure whenever none of this spec is open (SPEC-31)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schedule: Literal["when_flat"] = Field(description="Selects this entry schedule.")
    cooldown_trading_days: int = Field(
        default=1, ge=0,
        description="Trading days to wait after a structure is closed by a close action or by expiry before "
                    "re-entering. Default 1, so a close and a re-entry don't happen at the same step. It does not "
                    "delay a roll, which re-establishes the structure immediately.")
    max_open: int = Field(default=1, ge=1, description=_MAX_OPEN)


class EveryNTradingDaysParams(BaseModel):
    """``every_n_trading_days``: open a structure every ``n`` trading days (SPEC-32)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schedule: Literal["every_n_trading_days"] = Field(description="Selects this entry schedule.")
    n: int = Field(ge=1, description="Trading days between entries, counted on the trading calendar from the run's "
                                     "first step (ENG-4). A due day that the run skips as a missing day has no entry.")
    max_open: int = Field(default=1, ge=1, description=_MAX_OPEN)


class WeekdaysParams(BaseModel):
    """``weekdays``: open a structure on the listed weekdays (SPEC-33)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schedule: Literal["weekdays"] = Field(description="Selects this entry schedule.")
    weekdays: list[Weekday] = Field(min_length=1, description="Weekdays on which to enter, for example [MON, WED].")
    holiday_shift: HolidayShift = Field(
        default=HolidayShift.SKIP,
        description="When a listed weekday is not a trading day: skip (default) enters nothing that week for that "
                    "day; next enters on the next trading day.")
    max_open: int = Field(default=1, ge=1, description=_MAX_OPEN)


ENTRY_SCHEDULE_PARAMS: tuple[type[BaseModel], ...] = (OnceParams, WhenFlatParams, EveryNTradingDaysParams,
                                                       WeekdaysParams)
"""Every entry schedule's parameter model, in the order the requirements list them."""
