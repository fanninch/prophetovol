"""The exception hierarchy shared by the service, the engine and the clients.

Clients map these to readable messages (the CLI) or HTTP statuses (the API, NFR-3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ProphetoVolError(Exception):
    """Base class of every error ProphetoVol raises on purpose."""


class NotFoundError(ProphetoVolError):
    """A requested entity (import, spec version, run, job, ...) does not exist."""


class ImmutableEntityError(ProphetoVolError):
    """An attempt to change something that is immutable once published or finished (VER-1)."""


class ConfigurationError(ProphetoVolError):
    """Reference data or configuration is missing or inconsistent."""


class PointInTimeError(ProphetoVolError):
    """The engine asked for data stamped after the current step's as-of time (ARC-3)."""


class HomeLockedError(ProphetoVolError):
    """The home directory's databases are held by another process (INT-41)."""


@dataclass(frozen=True)
class ValidationIssue:
    """One validation finding, located by a field path.

    :param path: Dotted path of the field the finding is about, for example ``legs.0.strike.target``;
        empty for the object as a whole.
    :param message: What is wrong and, where possible, how to fix it.
    """

    path: str
    message: str

    def __str__(self) -> str:
        """Return ``path: message``, or the message alone when there is no path."""
        return f"{self.path}: {self.message}" if self.path else self.message


class ValidationFailed(ProphetoVolError):
    """Input failed validation; carries every finding with its field path (SPEC-80).

    :param issues: The findings, in the order they were found.
    """

    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = list(issues)
        lines = "\n".join(f"  - {issue}" for issue in self.issues)
        super().__init__(f"validation failed with {len(self.issues)} issue(s):\n{lines}")

    @classmethod
    def from_pydantic(cls, error: Any) -> ValidationFailed:
        """Convert a pydantic ``ValidationError`` into located issues.

        :param error: The pydantic error.
        :returns: One issue per pydantic error, with its dotted field path.
        """
        return cls([ValidationIssue(".".join(str(part) for part in e["loc"]), e["msg"]) for e in error.errors()])
