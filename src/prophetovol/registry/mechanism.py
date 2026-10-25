"""Registries of named, interchangeable implementations (ARC-5, REG-1 to REG-3).

A :class:`Registry` holds the implementations of one component type, for example the settlement
sources. Each implementation declares a name, a one-paragraph description, a pydantic parameter
model with a description on every field, and an implementation version (REG-2). Specs and
configurations refer to implementations by name; the service, the CLI and the API list and
describe them, with JSON Schemas, from here (REG-3).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from prophetovol.core.errors import ConfigurationError, NotFoundError

T = TypeVar("T")

_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class Implementation(Generic[T]):
    """One registered implementation.

    :param name: Its name, in lower snake case; what specs and configurations refer to.
    :param description: One paragraph saying what it does, written for a reader with no other context.
    :param params: The pydantic model of its parameters; every field has a description.
    :param version: The implementation's version, recorded on runs (REG-2).
    :param target: The implementation itself: a class or a function.
    """

    name: str
    description: str
    params: type[BaseModel]
    version: str
    target: T


class ImplementationInfo(BaseModel):
    """What the service, the CLI and the API show about one implementation (REG-3)."""

    model_config = ConfigDict(frozen=True)

    kind: str = Field(description="The registry the implementation belongs to, for example settlement_source.")
    name: str = Field(description="The implementation's name, as specs and configurations refer to it.")
    description: str = Field(description="What the implementation does.")
    version: str = Field(description="The implementation's version, recorded on runs.")
    params_schema: dict[str, Any] = Field(description="The JSON Schema of the implementation's parameters.")


class RegistryInfo(BaseModel):
    """What the service, the CLI and the API show about one registry (REG-3)."""

    model_config = ConfigDict(frozen=True)

    kind: str = Field(description="The registry's name, for example settlement_source.")
    description: str = Field(description="What the component type is for.")
    implementations: list[str] = Field(description="Names of the registered implementations, in alphabetical order.")


class Registry(Generic[T]):
    """The named implementations of one component type.

    :param kind: The registry's name in lower snake case, for example ``settlement_source``.
    :param description: What the component type is for.
    """

    def __init__(self, kind: str, description: str) -> None:
        if not _NAME.match(kind):
            raise ConfigurationError(f"registry name {kind!r} must be lower snake case")
        self.kind = kind
        self.description = description
        self._items: dict[str, Implementation[T]] = {}

    def register(self, name: str, *, description: str, params: type[BaseModel],
                 version: str) -> Callable[[T], T]:
        """Return a decorator registering a class or function under ``name``.

        :param name: The implementation's name, in lower snake case and unique in this registry.
        :param description: One paragraph saying what it does.
        :param params: Its pydantic parameter model; every field must have a description (REG-2).
        :param version: Its implementation version.
        :returns: A decorator that registers its argument and returns it unchanged.
        :raises ConfigurationError: If the name is invalid or taken, the description is empty, or a
            parameter has no description.
        """
        if not _NAME.match(name):
            raise ConfigurationError(f"{self.kind}: name {name!r} must be lower snake case")
        if name in self._items:
            raise ConfigurationError(f"{self.kind}: {name!r} is already registered")
        if not description.strip():
            raise ConfigurationError(f"{self.kind}.{name}: a description is required")
        if not version.strip():
            raise ConfigurationError(f"{self.kind}.{name}: a version is required")
        undocumented = [f for f, info in params.model_fields.items() if not (info.description or "").strip()]
        if undocumented:
            raise ConfigurationError(f"{self.kind}.{name}: parameters without a description: {undocumented}")

        def decorator(target: T) -> T:
            """Register ``target`` and return it unchanged.

            :param target: The class or function implementing the component.
            """
            self._items[name] = Implementation(name, description.strip(), params, version, target)
            return target

        return decorator

    def get(self, name: str) -> Implementation[T]:
        """Look up an implementation by name.

        :param name: The implementation's name.
        :returns: The implementation.
        :raises NotFoundError: If no implementation has that name; the message lists the known names.
        """
        try:
            return self._items[name]
        except KeyError:
            known = ", ".join(self.names()) or "none"
            raise NotFoundError(f"no {self.kind} named {name!r} (known: {known})") from None

    def names(self) -> list[str]:
        """The registered names, in alphabetical order.

        :returns: The names.
        """
        return sorted(self._items)

    def describe(self, name: str) -> ImplementationInfo:
        """Describe one implementation, with the JSON Schema of its parameters.

        :param name: The implementation's name.
        :returns: Its description.
        """
        impl = self.get(name)
        return ImplementationInfo(kind=self.kind, name=impl.name, description=impl.description,
                                  version=impl.version, params_schema=impl.params.model_json_schema())

    def info(self) -> RegistryInfo:
        """Describe the registry and list its implementations.

        :returns: The registry's description.
        """
        return RegistryInfo(kind=self.kind, description=self.description, implementations=self.names())
