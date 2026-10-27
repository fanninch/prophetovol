"""Parameter models of the expiration and strike selectors (SPEC-10 to SPEC-28).

Each model carries its ``selector`` name as a literal, so a spec's ``expiration`` and ``strike``
fields are discriminated unions of these models (§4.5 of the plan). The selection behavior is in
:mod:`prophetovol.engine.selection`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from prophetovol.core.types import SettlementStyle


class Weekday(StrEnum):
    """A day of the week, as written in specs (``MON`` … ``SUN``)."""

    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class ExpirationTieBreak(StrEnum):
    """Which expiration wins when two are equally near the target."""

    LATER = "later"
    EARLIER = "earlier"


class StrikeTieBreak(StrEnum):
    """Which strike wins when two are equally near the target delta (SPEC-20)."""

    FURTHER_OTM = "further_otm"
    NEARER_OTM = "nearer_otm"


class OnNoMatch(StrEnum):
    """What happens when a strike selector finds no contract within its tolerance (SPEC-25)."""

    SKIP_ENTRY = "skip_entry"
    NEAREST_ANY = "nearest_any"


class ExpirationFilter(BaseModel):
    """Which expirations a selector may choose from (SPEC-14). Every condition given must hold."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    standard_monthly_only: bool = Field(
        default=False,
        description="Only standard monthly expirations: those whose settlement date is the third Friday of the "
                    "month, or the trading day before it when that Friday is a holiday. Saturday-dated monthlies "
                    "(before 2015) settle on that Friday and count. Decided by date whatever the root; add "
                    "settlement_styles: [AM] for the AM-settled monthlies only.")
    weekdays: list[Weekday] | None = Field(
        default=None, min_length=1,
        description="Allowed weekdays of the expiration date, for example [FRI]. Null allows every weekday.")
    roots: list[str] | None = Field(
        default=None, min_length=1,
        description="Allowed normalized option roots, for example [SPXW] (REF-1). Null allows every root.")
    settlement_styles: list[SettlementStyle] | None = Field(
        default=None, min_length=1,
        description="Allowed settlement styles, AM and/or PM. Null allows both.")


class TargetDaysParams(BaseModel):
    """``target_days``: the expiration whose calendar days to expiry is nearest ``days`` (SPEC-10)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    selector: Literal["target_days"] = Field(description="Selects this expiration selector.")
    days: float = Field(ge=0, description="Target calendar days to expiry, fractional (CONV-1), for example 45, "
                                          "or 0.5 for a same-day expiration.")
    min_days: float | None = Field(
        default=None, ge=0,
        description="Fewest calendar days to expiry an eligible expiration may have. Null means days − 10, floored at 0.")
    max_days: float | None = Field(
        default=None, ge=0,
        description="Most calendar days to expiry an eligible expiration may have. Null means days + 10.")
    tie_break: ExpirationTieBreak = Field(
        default=ExpirationTieBreak.LATER,
        description="Which of two expirations equally near the target wins: later (default) or earlier.")
    filter: ExpirationFilter = Field(default_factory=ExpirationFilter,
                                     description="Which expirations are eligible (SPEC-14).")

    def window(self) -> tuple[float, float]:
        """The eligible range of calendar days to expiry, with the defaults applied.

        :returns: ``(min_days, max_days)``.
        """
        low = max(self.days - 10.0, 0.0) if self.min_days is None else self.min_days
        high = self.days + 10.0 if self.max_days is None else self.max_days
        return low, high

    @model_validator(mode="after")
    def _window_is_not_empty(self) -> TargetDaysParams:
        """Reject a window whose lower bound is above its upper bound.

        :returns: The parameters, unchanged.
        """
        low, high = self.window()
        if low > high:
            raise ValueError(f"min_days ({low:g}) is above max_days ({high:g}): no expiration could be eligible")
        return self


class TradingDaysOutParams(BaseModel):
    """``trading_days_out``: the expiration ``n`` trading days out (SPEC-11)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    selector: Literal["trading_days_out"] = Field(description="Selects this expiration selector.")
    n: int = Field(ge=0, description="Trading days to expiry (CONV-2) wanted: 1 is the next trading day's "
                                     "expiration, 0 an expiration settling today.")
    tolerance: int = Field(default=0, ge=0,
                           description="How many trading days away from n an expiration may be and still match.")
    tie_break: ExpirationTieBreak = Field(
        default=ExpirationTieBreak.LATER,
        description="Which of two expirations equally near n wins: later (default) or earlier.")
    filter: ExpirationFilter = Field(default_factory=ExpirationFilter,
                                     description="Which expirations are eligible (SPEC-14).")


class NthExpirationParams(BaseModel):
    """``nth_expiration``: the n-th eligible expiration after the as-of time (SPEC-12)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    selector: Literal["nth_expiration"] = Field(description="Selects this expiration selector.")
    n: int = Field(ge=1, description="Which eligible expiration: 1 is the next one. Only expirations passing the "
                                     "filter are counted.")
    filter: ExpirationFilter = Field(default_factory=ExpirationFilter,
                                     description="Which expirations are eligible and counted (SPEC-14).")


class SameAsLegParams(BaseModel):
    """``same_as_leg``: the same expiration as another leg (SPEC-13)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    selector: Literal["same_as_leg"] = Field(description="Selects this expiration selector.")
    leg: str = Field(description="Id of the leg whose expiration this leg uses; it is selected first (SPEC-3).")


class NextAfterLegParams(BaseModel):
    """``next_after_leg``: the first eligible expiration strictly after another leg's (SPEC-13)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    selector: Literal["next_after_leg"] = Field(description="Selects this expiration selector.")
    leg: str = Field(description="Id of the leg whose expiration this leg's must follow; it is selected first.")
    filter: ExpirationFilter = Field(default_factory=ExpirationFilter,
                                     description="Which expirations are eligible (SPEC-14).")


EXPIRATION_SELECTOR_PARAMS: tuple[type[BaseModel], ...] = (
    TargetDaysParams, TradingDaysOutParams, NthExpirationParams, SameAsLegParams, NextAfterLegParams)
"""Every expiration selector's parameter model, in the order the requirements list them."""


class DeltaParams(BaseModel):
    """``delta``: the strike whose absolute delta is nearest ``target`` (SPEC-20)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    selector: Literal["delta"] = Field(description="Selects this strike selector.")
    target: float = Field(gt=0, lt=1, description="Target absolute delta (CONV-4): 0.25 means a 25-delta call "
                                                  "(delta 0.25) or a 25-delta put (delta −0.25).")
    tolerance: float = Field(default=0.05, ge=0,
                             description="Largest absolute-delta distance from target that still matches.")
    tie_break: StrikeTieBreak = Field(
        default=StrikeTieBreak.FURTHER_OTM,
        description="Which of two strikes equally near the target wins: further_otm (default) or nearer_otm.")
    on_no_match: OnNoMatch = Field(
        default=OnNoMatch.SKIP_ENTRY,
        description="skip_entry (default): no structure opens at this step. nearest_any: take the nearest eligible "
                    "strike regardless of tolerance, with a warning event (SPEC-25).")


class AtmParams(BaseModel):
    """``atm``: the 50-delta strike of the leg's own type (SPEC-21, CONV-5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    selector: Literal["atm"] = Field(description="Selects this strike selector.")
    tolerance: float = Field(default=0.05, ge=0,
                             description="Largest absolute-delta distance from 0.50 that still matches.")
    tie_break: StrikeTieBreak = Field(
        default=StrikeTieBreak.FURTHER_OTM,
        description="Which of two strikes equally near 0.50 wins: further_otm (default) or nearer_otm.")
    on_no_match: OnNoMatch = Field(default=OnNoMatch.SKIP_ENTRY,
                                   description="What happens when no strike is within tolerance (SPEC-25).")


class ForwardParams(BaseModel):
    """``forward``: the strike nearest the series forward (SPEC-22)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    selector: Literal["forward"] = Field(description="Selects this strike selector.")
    tolerance_points: float | None = Field(
        default=None, ge=0,
        description="Largest distance in index points from the forward that still matches. Null means the usual "
                    "strike spacing around the forward in that expiration (the most common gap between adjacent "
                    "listed strikes there), so a hole in the chain skips the entry rather than taking a distant strike.")
    on_no_match: OnNoMatch = Field(default=OnNoMatch.SKIP_ENTRY,
                                   description="What happens when no strike is within tolerance (SPEC-25).")


class SameStrikeAsParams(BaseModel):
    """``same_strike_as``: another leg's strike, listed in this leg's expiration (SPEC-23)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    selector: Literal["same_strike_as"] = Field(description="Selects this strike selector.")
    leg: str = Field(description="Id of the leg whose strike this leg uses; it is selected first (SPEC-3).")
    tolerance_points: float = Field(default=0.0, ge=0,
                                    description="Largest distance in index points from that strike that still "
                                                "matches; 0 (default) means exactly the same strike.")
    on_no_match: OnNoMatch = Field(default=OnNoMatch.SKIP_ENTRY,
                                   description="What happens when no strike is within tolerance (SPEC-25).")


class StrikeOffsetParams(BaseModel):
    """``strike_offset``: another leg's strike plus an offset, to the nearest listed strike (SPEC-24)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    selector: Literal["strike_offset"] = Field(description="Selects this strike selector.")
    leg: str = Field(description="Id of the leg whose strike the offset starts from; it is selected first.")
    points: float | None = Field(default=None,
                                 description="Signed offset in index points, for example 50 or −50. Give points or "
                                             "percent, not both.")
    percent: float | None = Field(default=None,
                                  description="Signed offset as a percentage of that strike, for example 2.5 for "
                                              "+2.5%. Give points or percent, not both.")
    tolerance_points: float | None = Field(
        default=None, ge=0,
        description="Largest distance in index points from the offset strike that still matches. Null means the "
                    "usual strike spacing around it in that expiration.")
    on_no_match: OnNoMatch = Field(default=OnNoMatch.SKIP_ENTRY,
                                   description="What happens when no strike is within tolerance (SPEC-25).")

    @model_validator(mode="after")
    def _one_offset(self) -> StrikeOffsetParams:
        """Require exactly one of ``points`` and ``percent``.

        :returns: The parameters, unchanged.
        """
        if (self.points is None) == (self.percent is None):
            raise ValueError("give exactly one of points and percent")
        return self


STRIKE_SELECTOR_PARAMS: tuple[type[BaseModel], ...] = (
    DeltaParams, AtmParams, ForwardParams, SameStrikeAsParams, StrikeOffsetParams)
"""Every strike selector's parameter model, in the order the requirements list them."""
