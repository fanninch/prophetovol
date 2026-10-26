"""The quality report of an import (DATA-20, DATA-21): counts and examples per check, per date."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Severity(StrEnum):
    """How a check's findings affect the import."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class DateCount(BaseModel):
    """How often a check fired on one snapshot date."""

    as_of_date: date | None = Field(description="The snapshot date; null when the date itself could not be parsed.")
    count: int = Field(ge=0, description="Number of rows (or expirations, where the check says so) that the check flagged.")


class QualityCheck(BaseModel):
    """One check's findings."""

    name: str = Field(description="The check's id, for example crossed_quote.")
    severity: Severity = Field(description="error blocks the import; warning and info do not.")
    description: str = Field(description="What the check looks for, for people.")
    count: int = Field(ge=0, description="Total findings across the import.")
    by_date: list[DateCount] = Field(default_factory=list, description="Findings per snapshot date, in date order.")
    examples: list[dict[str, Any]] = Field(default_factory=list,
                                           description="Up to five example rows (or details) that the check flagged.")


class QualityReport(BaseModel):
    """Everything validation found in an import (DATA-20). Stored with the import permanently (DATA-21)."""

    rows: int = Field(ge=0, description="Rows read from the import's files.")
    dates: int = Field(ge=0, description="Distinct snapshot dates in the import.")
    first_as_of_date: date | None = Field(default=None, description="First snapshot date.")
    last_as_of_date: date | None = Field(default=None, description="Last snapshot date.")
    checks: list[QualityCheck] = Field(default_factory=list, description="Every check that found something, in check order.")

    @property
    def errors(self) -> list[QualityCheck]:
        """The checks with error severity that found something; any one blocks the import."""
        return [c for c in self.checks if c.severity is Severity.ERROR and c.count]

    @property
    def warnings(self) -> list[QualityCheck]:
        """The checks with warning severity that found something."""
        return [c for c in self.checks if c.severity is Severity.WARNING and c.count]

    def check(self, name: str) -> QualityCheck | None:
        """Find a check's findings by name.

        :param name: The check's id.
        :returns: The findings, or ``None`` if the check found nothing.
        """
        return next((c for c in self.checks if c.name == name), None)

    def flags_by_date(self) -> dict[date, list[str]]:
        """The warning and error checks that fired on each date, for the data versions' quality flags.

        :returns: Check names per date, in check order.
        """
        flags: dict[date, list[str]] = {}
        for c in self.checks:
            if c.severity is Severity.INFO:
                continue
            for dc in c.by_date:
                if dc.as_of_date is not None and dc.count:
                    flags.setdefault(dc.as_of_date, []).append(c.name)
        return flags
