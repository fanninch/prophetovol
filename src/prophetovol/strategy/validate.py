"""The dry-run validation of a strategy spec (SPEC-80).

:func:`validate_spec` returns every error and warning at once, each with a field path such as
``legs[1].strike.leg`` and a message. Publishing applies the same function, so a spec that
validates here publishes. It checks:

* schema validity, with pydantic's error locations turned into spec field paths;
* unique leg ids and trigger names, and references to existing legs, never to the leg itself;
* no reference cycles, and the order in which legs are selected (SPEC-3);
* hedge band bounds (in the band's own model) and roots allowed by the underlying (REF-1);
* SPEC-52 (an error) and SPEC-53 (a warning);
* units on day conditions: a warning when ``unit`` is left out, since ``calendar_days`` is then assumed.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

import pydantic
from pydantic import BaseModel, ConfigDict, Field

from prophetovol.core.errors import ValidationFailed, ValidationIssue
from prophetovol.core.records import DefinitionVersion
from prophetovol.core.types import SettlementStyle
from prophetovol.reference.models import Underlying
from prophetovol.registry.params.selection import NextAfterLegParams, SameAsLegParams, TargetDaysParams
from prophetovol.registry.params.triggers import (LegDaysToExpiryAtOrBelowParams,
                                                  StructureMinDaysToExpiryAtOrBelowParams)
from prophetovol.strategy.model import DISCRIMINATORS, Leg, StrategySpec

SPEC_52_MESSAGE = ("AM-settled contracts cannot be held to expiration: no AM settlement source is configured. "
                   "Restrict this leg to PM-settled roots, or add a closing trigger.")
"""SPEC-52's message, word for word."""

_UNION_LABELS = {"expiration": "expiration selector", "strike": "strike selector", "entry": "entry schedule",
                 "any_of": "trigger condition", "hedge": "hedge rule", "sizing": "sizing method"}


class SpecIssue(BaseModel):
    """One finding of the dry run, located by a field path (SPEC-80)."""

    model_config = ConfigDict(frozen=True)

    severity: Literal["error", "warning"] = Field(description="error blocks publishing; warning does not.")
    path: str = Field(description="Where in the spec, for example legs[1].strike.leg; empty for the spec as a whole.")
    message: str = Field(description="What is wrong and, where possible, how to fix it.")


class SpecValidationReport(BaseModel):
    """The result of validating a spec: every error and warning at once (SPEC-80)."""

    model_config = ConfigDict(frozen=True)

    spec_id: str | None = Field(default=None, description="The spec's id, when it could be read.")
    errors: list[SpecIssue] = Field(default_factory=list, description="Findings that block publishing.")
    warnings: list[SpecIssue] = Field(default_factory=list, description="Findings that do not block publishing.")
    leg_order: list[str] = Field(default_factory=list,
                                 description="The order in which legs are selected: referenced legs first (SPEC-3). "
                                             "Empty when the spec has errors.")

    @property
    def ok(self) -> bool:
        """Whether the spec has no errors.

        :returns: True when it can be published.
        """
        return not self.errors


class SpecPublication(BaseModel):
    """The outcome of publishing a spec (VER-1, VER-2)."""

    model_config = ConfigDict(frozen=True)

    definition: DefinitionVersion = Field(description="The spec's latest version: the new one, or the existing one "
                                                      "when the content was unchanged.")
    created: bool = Field(description="Whether this call published a new version; false when the content was unchanged.")
    report: SpecValidationReport = Field(description="The validation report, with any warnings.")


class SpecInvalid(ValidationFailed):
    """A spec failed validation; carries the whole report, warnings included.

    :param report: The validation report, with at least one error.
    """

    def __init__(self, report: SpecValidationReport) -> None:
        self.report = report
        super().__init__([ValidationIssue(e.path, e.message) for e in report.errors])


def _path(loc: tuple[Any, ...], data: Any) -> str:
    """Turn a pydantic error location into a spec field path, leaving out union tags.

    :param loc: The location, for example ``('legs', 0, 'strike', 'delta', 'target')``.
    :param data: The input the location points into.
    :returns: The path, for example ``legs[0].strike.target``.
    """
    out, node = "", data
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
            node = node[part] if isinstance(node, list) and 0 <= part < len(node) else None
            continue
        if isinstance(node, dict) and part not in node and any(node.get(d) == part for d in DISCRIMINATORS):
            continue  # pydantic adds the chosen union member's tag to the location
        out += ("." if out else "") + str(part)
        node = node.get(part) if isinstance(node, dict) else None
    return out


def _schema_issue(error: Any, data: Any) -> SpecIssue:
    """One pydantic error as a located, readable issue.

    :param error: One entry of ``ValidationError.errors()``.
    :param data: The validated input.
    :returns: The issue.
    """
    path = _path(tuple(error["loc"]), data)
    message = error["msg"].removeprefix("Value error, ")
    field = [p for p in error["loc"] if isinstance(p, str)][-1:] or [""]
    label = _UNION_LABELS.get(field[0], "implementation")
    ctx = error.get("ctx") or {}
    if error["type"] == "union_tag_invalid":
        known = ", ".join(sorted(t.strip(" '") for t in ctx.get("expected_tags", "").split(",")))
        message = f"unknown {label} {ctx.get('tag')!r} (known: {known})"
    elif error["type"] == "union_tag_not_found":
        message = f"missing {ctx.get('discriminator', '').strip(chr(39))!r}: name the {label} to use"
    return SpecIssue(severity="error", path=path, message=message)


def leg_order(spec: StrategySpec) -> tuple[list[str], list[str] | None]:
    """The selection order of the legs, referenced legs first, keeping spec order where free.

    :param spec: A spec whose references all name other, existing legs.
    :returns: ``(order, None)``, or ``([], cycle)`` naming the legs of a reference cycle.
    """
    deps = {leg.id: set(leg.references()) for leg in spec.legs}
    order: list[str] = []
    remaining = [leg.id for leg in spec.legs]
    while remaining:
        ready = next((lid for lid in remaining if deps[lid] <= set(order)), None)
        if ready is None:
            # every remaining leg waits on another remaining leg: follow references to name a cycle
            path = [remaining[0]]
            while True:
                nxt = sorted(deps[path[-1]] - set(order))[0]
                if nxt in path:
                    return [], path[path.index(nxt):] + [nxt]
                path.append(nxt)
        order.append(ready)
        remaining.remove(ready)
    return order, None


def _can_select_am(leg: Leg, spec: StrategySpec, underlying: Underlying) -> bool:
    """Whether a leg's roots and expiration filter let it select an AM-settled root.

    :param leg: The leg.
    :param spec: Its spec (acyclic).
    :param underlying: The spec's underlying.
    :returns: True when an AM-settled contract could be selected.
    """
    am = {r.normalized_root for r in underlying.roots.values() if r.settlement_style is SettlementStyle.AM}
    allowed = set(leg.roots or underlying.normalized_roots())
    selector = leg.expiration
    flt = getattr(selector, "filter", None)
    if flt is not None:
        if flt.roots:
            allowed &= set(flt.roots)
        if flt.settlement_styles and SettlementStyle.AM not in flt.settlement_styles:
            allowed -= am
    if not allowed & am:
        return False
    if isinstance(selector, SameAsLegParams):
        return _can_select_am(spec.leg(selector.leg), spec, underlying)
    return True


def _expires_no_earlier(leg: Leg, other: Leg) -> bool:
    """Whether ``leg`` always expires on or after ``other``, as far as the spec shows.

    :param leg: The leg in question.
    :param other: The leg it is compared with.
    :returns: True when its selectors guarantee it.
    """
    exp, other_exp = leg.expiration, other.expiration
    if leg.id == other.id:
        return True
    if isinstance(exp, (SameAsLegParams, NextAfterLegParams)) and exp.leg == other.id:
        return True
    if isinstance(other_exp, SameAsLegParams) and other_exp.leg == leg.id:
        return True
    if isinstance(exp, TargetDaysParams) and isinstance(other_exp, TargetDaysParams):
        return exp.window()[0] >= other_exp.window()[1]
    return False


def _closed_before_expiry(leg: Leg, spec: StrategySpec) -> bool:
    """Whether a trigger closes or rolls the leg at least one trading day before expiry (SPEC-53).

    A days-to-expiry condition with ``days ≥ 1``, in trading or calendar days, counts when its trigger
    acts on this leg or the whole structure and the condition watches this leg, a leg it never outlives,
    or the structure's shortest-dated leg.

    :param leg: The leg.
    :param spec: Its spec.
    :returns: True when such a trigger exists.
    """
    for trigger in spec.triggers:
        scope = trigger.scope.leg
        if scope not in (None, leg.id):
            continue
        for cond in trigger.any_of:
            if isinstance(cond, StructureMinDaysToExpiryAtOrBelowParams) and cond.days >= 1:
                return True
            if isinstance(cond, LegDaysToExpiryAtOrBelowParams) and cond.days >= 1:
                if cond.leg == leg.id or (scope is None and _expires_no_earlier(leg, spec.leg(cond.leg))):
                    return True
    return False


def validate_spec(body: Any, underlyings: Mapping[str, Underlying]) -> tuple[SpecValidationReport, StrategySpec | None]:
    """Validate a spec without publishing it (SPEC-80).

    :param body: The spec as parsed from YAML or JSON.
    :param underlyings: The configured underlyings by symbol (REF-1).
    :returns: The report, and the spec when it has no errors (otherwise None).
    """
    spec_id = body.get("id") if isinstance(body, dict) and isinstance(body.get("id"), str) else None
    if not isinstance(body, dict):
        return SpecValidationReport(errors=[SpecIssue(severity="error", path="", message=(
            "a spec must be a mapping of fields (id, underlying, legs, …)"))]), None
    try:
        spec = StrategySpec.model_validate(body)
    except pydantic.ValidationError as exc:
        return SpecValidationReport(spec_id=spec_id, errors=[_schema_issue(e, body) for e in exc.errors()]), None

    errors: list[SpecIssue] = []
    warnings: list[SpecIssue] = []

    def error(path: str, message: str) -> None:
        """Record an error.

        :param path: Field path.
        :param message: Message.
        """
        errors.append(SpecIssue(severity="error", path=path, message=message))

    def warning(path: str, message: str) -> None:
        """Record a warning.

        :param path: Field path.
        :param message: Message.
        """
        warnings.append(SpecIssue(severity="warning", path=path, message=message))

    underlying = underlyings.get(spec.underlying)
    if underlying is None:
        error("underlying", f"unknown underlying {spec.underlying!r} (known: {', '.join(sorted(underlyings)) or 'none'})")

    ids = [leg.id for leg in spec.legs]
    for i, leg in enumerate(spec.legs):
        if leg.id in ids[:i]:
            error(f"legs[{i}].id", f"leg id {leg.id!r} is used by more than one leg")
    known = set(ids)
    for i, leg in enumerate(spec.legs):
        for field in ("expiration", "strike"):
            ref = getattr(getattr(leg, field), "leg", None)
            if ref is None:
                continue
            if ref == leg.id:
                error(f"legs[{i}].{field}.leg", f"leg {leg.id!r} cannot refer to itself")
            elif ref not in known:
                error(f"legs[{i}].{field}.leg", f"no leg named {ref!r} (legs: {', '.join(ids)})")
        if underlying is not None:
            roots = set(underlying.normalized_roots())
            for path, values in ((f"legs[{i}].roots", leg.roots),
                                 (f"legs[{i}].expiration.filter.roots", getattr(getattr(leg.expiration, "filter", None),
                                                                                "roots", None))):
                unknown = sorted(set(values or []) - roots)
                if unknown:
                    error(path, f"{', '.join(unknown)} not a normalized root of {underlying.symbol} "
                                f"(roots: {', '.join(sorted(roots))})")

    names = [t.name for t in spec.triggers]
    for i, trigger in enumerate(spec.triggers):
        if trigger.name in names[:i]:
            error(f"triggers[{i}].name", f"trigger name {trigger.name!r} is used by more than one trigger")
        if trigger.scope.leg is not None and trigger.scope.leg not in known:
            error(f"triggers[{i}].scope.leg", f"no leg named {trigger.scope.leg!r} (legs: {', '.join(ids)})")
        for j, cond in enumerate(trigger.any_of):
            ref = getattr(cond, "leg", None)
            if ref is not None and ref not in known:
                error(f"triggers[{i}].any_of[{j}].leg", f"no leg named {ref!r} (legs: {', '.join(ids)})")
            if "unit" in type(cond).model_fields and "unit" not in cond.model_fields_set:
                warning(f"triggers[{i}].any_of[{j}].unit", "unit not stated; calendar_days assumed. State "
                                                           "unit: calendar_days or unit: trading_days.")

    order: list[str] = []
    if not errors:
        order, cycle = leg_order(spec)
        if cycle:
            error("legs", f"legs refer to each other in a cycle: {' -> '.join(cycle)}")

    if not errors and underlying is not None:
        for i, leg in enumerate(spec.legs):
            if not _can_select_am(leg, spec, underlying):
                continue
            if leg.hold_to_expiration:
                error(f"legs[{i}].hold_to_expiration", SPEC_52_MESSAGE)
            elif not _closed_before_expiry(leg, spec):
                warning(f"legs[{i}]", (
                    f"leg {leg.id!r} can select AM-settled contracts and no trigger closes or rolls it at least one "
                    "trading day before expiry (a days-to-expiry condition with days >= 1), so the engine will "
                    "force-close it on its last trading day (SPEC-51). A calendar-day trigger can also miss over a "
                    "long weekend, and the forced close then applies."))

    report = SpecValidationReport(spec_id=spec.id, errors=errors, warnings=warnings,
                                  leg_order=order if not errors else [])
    return report, (spec if not errors else None)
