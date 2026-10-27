"""The run configuration (RUN-1) and named configuration templates (RUN-2).

A run is defined by a strategy version, a :class:`RunConfig` and, from M3, stress definitions. The
run stores the full resolved configuration and its hash (VER-3), so the reference alone
reconstructs what ran. Templates are named, versioned configurations kept for reuse.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from prophetovol.core.ids import content_hash
from prophetovol.core.types import Frequency
from prophetovol.registry.params.fills import CrossSpreadParams, MidParams, MidPlusFractionParams


class Rounding(StrEnum):
    """How structure units are rounded (SPEC-72); the hedge is never rounded (SPEC-62)."""

    WHOLE = "whole"
    FRACTIONAL = "fractional"


class StressMode(StrEnum):
    """How attached stress definitions act on a run (STR-30)."""

    MONITOR = "monitor"
    SCALE_TO_LIMIT = "scale_to_limit"
    HALT_RUN = "halt_run"


_STRESS_MODE = (
    "How attached stress definitions act on the run's opening orders (STR-30 to STR-35). "
    "monitor (default): stress is computed and reported at every step and never affects trades; steps at which a "
    "gated mode would have acted are flagged with what it would have done. "
    "scale_to_limit: each step's opening orders (entries and the opening sides of rolls) are reduced to the largest "
    "size at which the post-trade book, including the hedge the new orders would need under the spec's hedge rule, "
    "stays within every attached loss limit; stress P&L is linear in size, so q_max = min(Q, min over scenarios with "
    "loss per unit l_s > 0 of (X − L_s) / l_s), rounded down under whole rounding; if no size passes the orders are "
    "skipped; an event is recorded either way. "
    "halt_run: if the step's opening orders would breach any attached limit they are not executed, the step's closing "
    "orders and hedges are, and the run ends with status halted, recording the scenario, the loss and the limit. "
    "Closing orders and hedge trades are never gated. A book that breaches a limit at a step with no opening orders "
    "is reported and flagged, with no forced reduction. With several definitions attached, an order must pass all "
    "their limits. Stress arrives in milestone M3; until then only monitor is accepted.")


class RunConfig(BaseModel):
    """The configuration of one run (RUN-1). Every field has a default except the dates and the capital."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    underlying: str | None = Field(default=None, description="Symbol of the underlying; null (default) takes the "
                                                             "spec's. When given it must equal the spec's.")
    data_source: str = Field(default="ivolatility_eod",
                             description="The data source whose snapshots the run reads; it sets the snapshot timing "
                                         "(§7.2). Default ivolatility_eod.")
    frequency: Frequency = Field(default=Frequency.END_OF_DAY,
                                 description="How often the run steps; end_of_day, one step per trading day, is the "
                                             "only Phase 1 frequency (TIME-1).")
    start_date: date = Field(description="First date of the run; trading days from it are steps.")
    end_date: date = Field(description="Last date of the run, inclusive.")
    capital: float = Field(gt=0, description="Capital in dollars: the base of equity, returns and percentage limits "
                                             "(ENG-32). No interest or margin is modeled.")
    fill_model: Literal["mid", "cross_spread", "mid_plus_fraction"] = Field(
        default="cross_spread",
        description="How orders fill (ENG-40): mid; cross_spread (default), buying at the ask and selling at the bid; "
                    "or mid_plus_fraction, the mid plus fraction of the half-spread against the trader.")
    fraction: float | None = Field(default=None, ge=0, le=1,
                                   description="For mid_plus_fraction only, and required there: the share of the "
                                               "half-spread paid, from 0 (the mid) to 1 (crossing the spread).")
    commission_per_contract: float = Field(default=0.0, ge=0,
                                           description="Commission in dollars per option contract per side (ENG-42). "
                                                       "Default 0: set it to your all-in broker and exchange fee.")
    hedge_cost_bps: float = Field(default=0.0, ge=0,
                                  description="Hedge cost in basis points of traded hedge notional (ENG-42). Default 0.")
    rounding: Rounding = Field(default=Rounding.WHOLE,
                               description="Rounding of structure units (SPEC-72): whole (default) rounds down and skips "
                                           "an entry below one unit with an event; fractional keeps fractions. The hedge "
                                           "is never rounded.")
    stress_mode: StressMode = Field(default=StressMode.MONITOR, description=_STRESS_MODE)
    stress_discount_rate: float = Field(default=0.0,
                                        description="Continuously compounded rate r in stress revaluation's discount "
                                                    "factor exp(−rT) (STR-20), as a decimal. Default 0.")
    stale_mark_warning_steps: int = Field(default=5, ge=1,
                                          description="After this many consecutive steps marked at a stale price, a "
                                                      "warning event is recorded at each further stale step (ENG-21). "
                                                      "Default 5.")
    allow_missing_days: bool = Field(default=False,
                                     description="Skip trading days without an active snapshot instead of refusing the "
                                                 "run (RUN-11). Skipped days flag the next step; PM-settled contracts "
                                                 "settling on a skipped day are closed at the step before (SPEC-55). "
                                                 "Default false.")
    label: str = Field(default="", description="A short name for the run, for you.")
    notes: str = Field(default="", description="Free text about the run, for you.")

    @model_validator(mode="after")
    def _consistent(self) -> RunConfig:
        """Check the date range, the fill model's fraction and the stress mode.

        :returns: The configuration, unchanged.
        """
        if self.start_date > self.end_date:
            raise ValueError(f"start_date {self.start_date} is after end_date {self.end_date}")
        if self.fill_model == "mid_plus_fraction" and self.fraction is None:
            raise ValueError("fill_model mid_plus_fraction needs a fraction between 0 and 1")
        if self.fill_model != "mid_plus_fraction" and self.fraction is not None:
            raise ValueError(f"fraction applies only to mid_plus_fraction, not {self.fill_model}")
        if self.stress_mode is not StressMode.MONITOR:
            raise ValueError(f"stress_mode {self.stress_mode} arrives with stress in milestone M3; use monitor")
        return self

    def resolved(self, spec_underlying: str) -> RunConfig:
        """This configuration with its defaults resolved against the spec (VER-3).

        :param spec_underlying: The spec's underlying.
        :returns: The configuration with ``underlying`` set.
        :raises ValueError: If the configuration names a different underlying.
        """
        if self.underlying is not None and self.underlying != spec_underlying:
            raise ValueError(f"the configuration's underlying {self.underlying} differs from the spec's {spec_underlying}")
        return self.model_copy(update={"underlying": spec_underlying})

    def config_hash(self) -> str:
        """The SHA-256 of the configuration's canonical JSON (VER-3), independent of key order.

        :returns: 64 hexadecimal characters.
        """
        return content_hash(self.model_dump(mode="json"))

    def fill_model_params(self) -> MidParams | CrossSpreadParams | MidPlusFractionParams:
        """The fill model's registry parameters (ENG-40).

        :returns: The parameter model of the configured fill model.
        """
        if self.fill_model == "mid":
            return MidParams(fill_model="mid")
        if self.fill_model == "cross_spread":
            return CrossSpreadParams(fill_model="cross_spread")
        return MidPlusFractionParams(fill_model="mid_plus_fraction", fraction=self.fraction)


class RunConfigTemplate(BaseModel):
    """A named, versioned run configuration kept for reuse (RUN-2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", max_length=100,
                      description="The template's name; versions are published under it.")
    description: str = Field(default="", description="What the template is for, for people.")
    config: RunConfig = Field(description="The configuration. A run started from the template may override its dates.")
