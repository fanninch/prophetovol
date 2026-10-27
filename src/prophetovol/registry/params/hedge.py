"""Parameter models of the hedge rules (SPEC-60 to SPEC-64).

Each model carries its ``rule`` name as a literal, so a spec's ``hedge`` field is a discriminated
union of these models. The behavior is in :mod:`prophetovol.engine.hedging`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NoHedgeParams(BaseModel):
    """``none``: no hedging (SPEC-60)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule: Literal["none"] = Field(description="Selects this hedge rule.")


class BandParams(BaseModel):
    """``band``: keep the structure's net delta per unit within a band (SPEC-61).

    Net delta per unit is ``(Σ q_i · δ_i + h / m) / N``: leg quantities ``q_i`` in signed contracts,
    the snapshot's deltas ``δ_i``, the hedge holding ``h`` in index units, multiplier ``m`` and ``N``
    structure units. After the step's option trades, if it is outside ``[lower, upper]``, the hedge
    is traded so it equals ``target``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule: Literal["band"] = Field(description="Selects this hedge rule.")
    scope: Literal["structure"] = Field(default="structure",
                                        description="What the band applies to; structure is the only Phase 1 scope.")
    lower: float = Field(description="Lowest net delta per unit left unhedged, for example 0.0. lower ≤ target ≤ upper.")
    upper: float = Field(description="Highest net delta per unit left unhedged, for example 0.08 (long 8 deltas per "
                                     "spread). lower = upper = target = 0 hedges to flat at every step.")
    target: float = Field(description="Net delta per unit the hedge restores when the measure leaves the band, for "
                                      "example 0.03.")

    @model_validator(mode="after")
    def _ordered_bounds(self) -> BandParams:
        """Require ``lower ≤ target ≤ upper``.

        :returns: The parameters, unchanged.
        """
        if not self.lower <= self.target <= self.upper:
            raise ValueError(f"the band needs lower <= target <= upper, got lower {self.lower:g}, "
                             f"target {self.target:g}, upper {self.upper:g}")
        return self


HEDGE_RULE_PARAMS: tuple[type[BaseModel], ...] = (NoHedgeParams, BandParams)
"""Every hedge rule's parameter model, in the order the requirements list them."""
