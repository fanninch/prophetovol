"""Parameter models of the fill models (ENG-40) and the constructor (ENG-2).

A run configuration names its fill model (RUN-1, plan Phase 10). The behavior is in
:mod:`prophetovol.engine.fills` and :mod:`prophetovol.engine.constructor`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MidParams(BaseModel):
    """``mid``: fill at the mid of the valid quote."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fill_model: Literal["mid"] = Field(description="Selects this fill model.")


class CrossSpreadParams(BaseModel):
    """``cross_spread``: buy at the ask, sell at the bid (the default fill model)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fill_model: Literal["cross_spread"] = Field(description="Selects this fill model.")


class MidPlusFractionParams(BaseModel):
    """``mid_plus_fraction``: fill at the mid plus a fraction of the half-spread against the trader."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fill_model: Literal["mid_plus_fraction"] = Field(description="Selects this fill model.")
    fraction: float = Field(ge=0, le=1, description="Share of the half-spread paid: 0 is the mid, 1 crosses the spread.")


FILL_MODEL_PARAMS: tuple[type[BaseModel], ...] = (MidParams, CrossSpreadParams, MidPlusFractionParams)
"""Every fill model's parameter model, in the order the requirements list them."""


class RulesParams(BaseModel):
    """``rules`` takes no parameters: it applies the run's strategy spec (ENG-2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
