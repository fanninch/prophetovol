"""Data lifecycle reports and selections (DATA-30 to DATA-70)."""

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from prophetovol.core.records import DataVersionRecord


class CommitChoice(StrEnum):
    """The three choices after reviewing an import."""

    REPLACE = "replace"
    ADD_NEW = "add_new"
    CANCEL = "cancel"


class DataSelection(BaseModel):
    """Select one import or an inclusive underlying/date range."""

    import_id: str | None = Field(default=None, description="Import to purge; mutually exclusive with a range.")
    underlying: str | None = Field(default=None, description="Underlying for a date range.")
    start: date | None = Field(default=None, description="First snapshot date, inclusive.")
    end: date | None = Field(default=None, description="Last snapshot date, inclusive.")

    @model_validator(mode="after")
    def _valid(self):
        if self.import_id is not None:
            if not self.import_id or any(x is not None for x in (self.underlying, self.start, self.end)):
                raise ValueError("choose an import OR an underlying and date range")
        elif not self.underlying or self.start is None or self.end is None or self.start > self.end:
            raise ValueError("supply an underlying and an inclusive range with start <= end")
        return self


class OverlapItem(BaseModel):
    """An incoming snapshot and the active snapshot it would replace."""

    incoming: DataVersionRecord = Field(description="Staged snapshot and its contract count.")
    active: DataVersionRecord | None = Field(default=None, description="Currently active snapshot, if any.")


class RunImpact(BaseModel):
    """Dates of one underlying read by an affected run."""

    run_id: str = Field(description="Run that read an affected version.")
    underlying: str = Field(description="Underlying whose data changed.")
    dates: list[date] = Field(description="Affected snapshot dates, sorted and unique.")


class ChangePreview(BaseModel):
    """Reviewable deletion or purge scope, including a stale-preview guard."""

    operation: Literal["delete", "purge"] = Field(description="Operation being reviewed.")
    selection: DataSelection = Field(description="Requested import or inclusive range.")
    versions: list[DataVersionRecord] = Field(description="Exactly the eligible versions affected.")
    runs: list[RunImpact] = Field(description="Runs that read those versions; results are retained.")
    token: str = Field(description="Content hash of the scope and impacts; rechecked before execution.")


class CoverageDay(BaseModel):
    """Coverage of a calendar day, including unexpected non-trading snapshots."""

    day: date = Field(description="Exchange calendar date.")
    trading_day: bool = Field(description="Whether the exchange trades on this date.")
    snapshots: list[DataVersionRecord] = Field(description="Active snapshots with import, counts and quality flags.")


class CoverageMonth(BaseModel):
    """Monthly coverage counts; multiple snapshots on a day count as one covered day."""

    month: str = Field(description="Calendar month as YYYY-MM.")
    trading_days: int = Field(description="Trading days in the requested part of the month.")
    covered_days: int = Field(description="Trading days with an active snapshot.")
    missing_days: int = Field(description="Trading days without an active snapshot.")
    non_trading_days: int = Field(description="Non-trading dates with active snapshots.")
    contracts: int = Field(description="Sum of contract counts across active snapshots.")
    flagged_days: int = Field(description="Dates with at least one snapshot quality flag.")


class CoverageReport(BaseModel):
    """Daily coverage and monthly summaries (DATA-70)."""

    underlying: str = Field(description="Underlying being inspected.")
    days: list[CoverageDay] = Field(description="Trading days and non-trading dates with data, in date order.")
    months: list[CoverageMonth] = Field(description="Monthly summaries in month order.")
