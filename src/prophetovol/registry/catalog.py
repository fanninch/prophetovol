"""Every registry, for discovery by the service, the CLI and the API (REG-3).

Registries are created here, empty. Implementations register themselves when their modules are
imported; :func:`all_registries` imports the built-in implementation modules first, so the
listing is complete whichever module was imported before.
"""

from __future__ import annotations

import importlib

from prophetovol.core.errors import NotFoundError
from prophetovol.registry.mechanism import Registry

SETTLEMENT_SOURCES: Registry = Registry(
    "settlement_source",
    "How a contract held to its expiry is settled, by settlement style (REF-20). Phase 1 has a source "
    "for PM-settled contracts only; AM-settled contracts are never held to expiration (REF-21).",
)
"""Settlement sources (REF-20)."""

EXPIRATION_SELECTORS: Registry = Registry(
    "expiration_selector",
    "How a leg chooses its expiration (SPEC-10 to SPEC-15): by calendar days, by trading days, by position in "
    "the list of eligible expirations, or relative to another leg's expiration.",
)
"""Expiration selectors (SPEC-10 to SPEC-15)."""

STRIKE_SELECTORS: Registry = Registry(
    "strike_selector",
    "How a leg chooses its strike within its expiration (SPEC-20 to SPEC-28): by delta, at the money, nearest "
    "the forward, or relative to another leg's strike.",
)
"""Strike selectors (SPEC-20 to SPEC-28)."""

ENTRY_SCHEDULES: Registry = Registry(
    "entry_schedule",
    "When a spec opens new structures (SPEC-30 to SPEC-35).",
)
"""Entry schedules (SPEC-30 to SPEC-35)."""

TRIGGER_CONDITIONS: Registry = Registry(
    "trigger_condition",
    "Conditions a trigger watches at each step (SPEC-41, SPEC-42). Phase 1 conditions read only the structure's "
    "own state and the calendar (REG-4).",
)
"""Trigger conditions (SPEC-41)."""

TRIGGER_ACTIONS: Registry = Registry(
    "trigger_action",
    "What a fired trigger does to its leg or structure (SPEC-43 to SPEC-45).",
)
"""Trigger actions (SPEC-43)."""

HEDGE_RULES: Registry = Registry(
    "hedge_rule",
    "How a structure's delta is hedged with the index (SPEC-60 to SPEC-64).",
)
"""Hedge rules (SPEC-60 to SPEC-64)."""

SIZING_METHODS: Registry = Registry(
    "sizing_method",
    "How many structure units an entry opens (SPEC-70 to SPEC-73).",
)
"""Sizing methods (SPEC-70 to SPEC-73)."""

FILL_MODELS: Registry = Registry(
    "fill_model",
    "At what price an order on a valid quote fills (ENG-40).",
)
"""Fill models (ENG-40)."""

CONSTRUCTORS: Registry = Registry(
    "constructor",
    "The component that turns a step's market view and book into orders with reasons (ENG-2).",
)
"""Constructors (ENG-2)."""

_REGISTRIES: tuple[Registry, ...] = (SETTLEMENT_SOURCES, EXPIRATION_SELECTORS, STRIKE_SELECTORS, ENTRY_SCHEDULES,
                                     TRIGGER_CONDITIONS, TRIGGER_ACTIONS, HEDGE_RULES, SIZING_METHODS, FILL_MODELS,
                                     CONSTRUCTORS)

_BUILTIN_MODULES = (
    "prophetovol.reference.settlement",
    "prophetovol.engine.selection",
    "prophetovol.engine.entries",
    "prophetovol.engine.triggers",
    "prophetovol.engine.hedging",
    "prophetovol.engine.sizing",
    "prophetovol.engine.fills",
    "prophetovol.engine.constructor",
)
"""Modules whose import registers the built-in implementations."""


def load_builtins() -> None:
    """Import the modules that register the built-in implementations (idempotent)."""
    for name in _BUILTIN_MODULES:
        importlib.import_module(name)


def all_registries() -> list[Registry]:
    """Every registry, with the built-in implementations registered, in alphabetical order.

    :returns: The registries.
    """
    load_builtins()
    return sorted(_REGISTRIES, key=lambda r: r.kind)


def get_registry(kind: str) -> Registry:
    """Look up a registry by name.

    :param kind: The registry's name, for example ``settlement_source``.
    :returns: The registry, with the built-in implementations registered.
    :raises NotFoundError: If there is no registry of that name.
    """
    for registry in all_registries():
        if registry.kind == kind:
            return registry
    known = ", ".join(r.kind for r in all_registries())
    raise NotFoundError(f"no registry named {kind!r} (known: {known})")
