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

_REGISTRIES: tuple[Registry, ...] = (SETTLEMENT_SOURCES,)

_BUILTIN_MODULES = (
    "prophetovol.reference.settlement",
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
