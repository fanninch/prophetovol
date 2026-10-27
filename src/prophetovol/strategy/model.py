"""The strategy specification (SPEC-1 to SPEC-3, SPEC-28, SPEC-40, SPEC-54).

A :class:`StrategySpec` is a structure definition and its management rules. Selector, schedule,
condition, hedge and sizing fields are discriminated unions of the registries' parameter models
(§4.5 of the plan), keyed on ``selector``, ``schedule``, ``condition``, ``rule`` and ``method``,
so their JSON Schemas are generated, never written by hand. This module imports parameter models
only, not the engine, so the API, the forms and the documentation can read it (decision 28).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from prophetovol.core.types import OptionType
from prophetovol.registry.params.hedge import HEDGE_RULE_PARAMS, NoHedgeParams
from prophetovol.registry.params.schedules import ENTRY_SCHEDULE_PARAMS
from prophetovol.registry.params.selection import EXPIRATION_SELECTOR_PARAMS, STRIKE_SELECTOR_PARAMS
from prophetovol.registry.params.sizing import SIZING_METHOD_PARAMS
from prophetovol.registry.params.triggers import TRIGGER_CONDITION_PARAMS

ExpirationSelector = Annotated[Union[EXPIRATION_SELECTOR_PARAMS], Field(discriminator="selector")]
"""Any expiration selector's parameters, chosen by ``selector``."""

StrikeSelector = Annotated[Union[STRIKE_SELECTOR_PARAMS], Field(discriminator="selector")]
"""Any strike selector's parameters, chosen by ``selector``."""

EntrySchedule = Annotated[Union[ENTRY_SCHEDULE_PARAMS], Field(discriminator="schedule")]
"""Any entry schedule's parameters, chosen by ``schedule``."""

TriggerCondition = Annotated[Union[TRIGGER_CONDITION_PARAMS], Field(discriminator="condition")]
"""Any trigger condition's parameters, chosen by ``condition``."""

HedgeRule = Annotated[Union[HEDGE_RULE_PARAMS], Field(discriminator="rule")]
"""Any hedge rule's parameters, chosen by ``rule``."""

SizingMethod = Annotated[Union[SIZING_METHOD_PARAMS], Field(discriminator="method")]
"""Any sizing method's parameters, chosen by ``method``."""

DISCRIMINATORS: tuple[str, ...] = ("selector", "schedule", "condition", "rule", "method")
"""The keys that choose an implementation inside a spec."""

_LEG_ID = r"^[A-Za-z][A-Za-z0-9_]*$"
_SPEC_ID = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"


class Side(StrEnum):
    """Long (bought) or short (sold); positive quantity is long (CONV-8)."""

    LONG = "long"
    SHORT = "short"


class ExpiryHandling(StrEnum):
    """What happens to the rest of a structure when one of its legs settles or is force-closed (SPEC-54)."""

    CLOSE_STRUCTURE = "close_structure"
    KEEP_REMAINING = "keep_remaining"
    ROLL_LEG = "roll_leg"


class QuoteFilters(BaseModel):
    """Quote filters applied to every leg's selection (SPEC-28)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    require_valid_quote: bool = Field(default=True, description="Only contracts with a valid quote (ask > 0, bid ≥ 0, "
                                                                "ask ≥ bid; ENG-20) are eligible. Default true.")
    min_bid: float = Field(default=0.05, ge=0, description="Lowest bid an eligible contract may have, in index points. "
                                                           "Default 0.05.")
    min_open_interest: int = Field(default=0, ge=0, description="Lowest open interest an eligible contract may have; "
                                                                "0 (default) means no filter.")
    exclude_vendor_flagged: bool = Field(default=False, description="Exclude rows with the vendor's * flag, whose "
                                                                    "meaning is unconfirmed. Default false.")


class Leg(BaseModel):
    """One leg of a structure (SPEC-2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=_LEG_ID, max_length=64,
                    description="The leg's id, unique within the spec; other legs and triggers refer to it.")
    option_type: OptionType = Field(description="call or put.")
    side: Side = Field(description="long or short.")
    ratio: int = Field(default=1, ge=1, description="Contracts of this leg per unit of the structure. Default 1.")
    expiration: ExpirationSelector = Field(description="How the leg chooses its expiration (SPEC-10 to SPEC-15), "
                                                       "for example {selector: target_days, days: 45}.")
    strike: StrikeSelector = Field(description="How the leg chooses its strike (SPEC-20 to SPEC-25), for example "
                                               "{selector: delta, target: 0.30}.")
    roots: list[str] | None = Field(default=None, min_length=1,
                                    description="Allowed normalized option roots, for example [SPXW] (REF-1). Null "
                                                "(default) allows every root of the underlying.")
    hold_to_expiration: bool = Field(default=False,
                                     description="Hold the leg to settlement. Allowed only for PM-settled roots: "
                                                 "AM-settled contracts are always closed on their last trading day "
                                                 "(SPEC-51, SPEC-52).")

    def references(self) -> list[str]:
        """The ids of the legs this leg's selectors refer to, in field order (SPEC-3).

        :returns: Leg ids, possibly repeated.
        """
        return [p.leg for p in (self.expiration, self.strike) if getattr(p, "leg", None) is not None]


class TriggerScope(BaseModel):
    """What a trigger acts on: ``structure``, or ``{leg: <id>}`` for one leg (SPEC-40).

    In a spec it is written as the word ``structure`` or as ``{leg: short_call}``, and exported the same way.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    leg: str | None = Field(default=None, description="The leg the trigger acts on; null means the whole structure.")

    @model_validator(mode="before")
    @classmethod
    def _from_text(cls, value: Any) -> Any:
        """Accept the word ``structure`` for the whole structure.

        :param value: The raw scope.
        :returns: Data for the model.
        """
        if value == "structure":
            return {}
        if isinstance(value, str):
            raise ValueError("scope must be structure or {leg: <id>}")
        return value

    @model_serializer
    def _to_spec_form(self) -> str | dict[str, str]:
        """Write the scope as a spec does: ``structure`` or ``{leg: <id>}``.

        :returns: The serialized scope.
        """
        return "structure" if self.leg is None else {"leg": self.leg}


class Trigger(BaseModel):
    """A trigger: conditions that, when any fires, close or roll a leg or the structure (SPEC-40)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=100, description="The trigger's name, unique within the spec; "
                                                                "events record it.")
    scope: TriggerScope = Field(description="structure, or {leg: <id>} for one leg.")
    action: Literal["close", "roll"] = Field(description="close or roll (SPEC-43). When several triggers fire at one "
                                                         "step, structure close wins, then structure roll, then leg "
                                                         "close, then leg roll (SPEC-44).")
    any_of: list[TriggerCondition] = Field(min_length=1, description="Conditions; any one of them fires the trigger "
                                                                     "(SPEC-41).")


class StrategySpec(BaseModel):
    """A strategy: a structure of legs and its management rules (SPEC-1).

    Published versions are immutable (VER-1); every change publishes a new version.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=_SPEC_ID, max_length=100, description="The spec's id; versions are published under it.")
    description: str = Field(default="", description="What the strategy does, for people.")
    underlying: str = Field(min_length=1, description="Symbol of the underlying, for example SPX (§7.1).")
    legs: list[Leg] = Field(min_length=1, description="The structure's legs, in order. Legs that refer to other legs "
                                                      "are selected after them (SPEC-3).")
    entry: EntrySchedule = Field(description="When structures are opened (SPEC-30 to SPEC-35), for example "
                                             "{schedule: when_flat}.")
    triggers: list[Trigger] = Field(default_factory=list, description="Close and roll rules (SPEC-40 to SPEC-46). "
                                                                      "Default none.")
    expiry_handling: ExpiryHandling = Field(
        default=ExpiryHandling.CLOSE_STRUCTURE,
        description="When a leg settles or is force-closed: close_structure (default) closes the remaining legs and the "
                    "hedge; keep_remaining keeps them open; roll_leg re-selects the expired leg (SPEC-54).")
    hedge: HedgeRule = Field(default_factory=lambda: NoHedgeParams(rule="none"),
                             description="How the structure is delta hedged (SPEC-60 to SPEC-64). Default "
                                         "{rule: none}.")
    sizing: SizingMethod = Field(description="How many units an entry opens (SPEC-70 to SPEC-73), for example "
                                             "{method: contracts, quantity: 10}.")
    selection: QuoteFilters = Field(default_factory=QuoteFilters,
                                    description="Quote filters applied to every leg's selection (SPEC-28).")

    def leg(self, leg_id: str) -> Leg:
        """Look up a leg by id.

        :param leg_id: The leg's id.
        :returns: The leg.
        :raises KeyError: If the spec has no such leg.
        """
        for leg in self.legs:
            if leg.id == leg_id:
                return leg
        raise KeyError(leg_id)
