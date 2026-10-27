"""Parameter models of the sizing methods (SPEC-70 to SPEC-73).

Each model carries its ``method`` name as a literal, so a spec's ``sizing`` field is a
discriminated union of these models. The behavior is in :mod:`prophetovol.engine.sizing`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ContractsParams(BaseModel):
    """``contracts``: a fixed number of structure units per entry (SPEC-70)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    method: Literal["contracts"] = Field(description="Selects this sizing method.")
    quantity: float = Field(gt=0, description="Structure units per entry; leg i trades quantity × ratio_i contracts. "
                                              "Rounded as the run configuration says (whole or fractional, SPEC-72).")


class NotionalParams(BaseModel):
    """``notional``: units from a dollar notional at the entry step's index level (SPEC-71)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    method: Literal["notional"] = Field(description="Selects this sizing method.")
    notional: float = Field(gt=0, description="Dollars of index exposure per entry: units = notional / (S × m), with S "
                                              "the index level at the entry step and m the multiplier.")


SIZING_METHOD_PARAMS: tuple[type[BaseModel], ...] = (ContractsParams, NotionalParams)
"""Every sizing method's parameter model, in the order the requirements list them."""
