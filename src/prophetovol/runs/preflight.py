"""Pre-flight: everything a run needs, checked before it starts (RUN-10 to RUN-12).

Pre-flight returns every problem at once, as errors (which block the run) and warnings (which do
not), and fixes the run's step schedule. It reads the catalog only (data versions, imports), never
the market files. The data versions it lists are the ones the run will read (decision 30).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from prophetovol.core.errors import ConfigurationError, ValidationFailed, ValidationIssue
from prophetovol.core.records import DataVersionRecord
from prophetovol.data.schema import MARKET_COLUMNS
from prophetovol.engine.schedule import Step, StepSchedule
from prophetovol.engine.view import ENGINE_COLUMNS
from prophetovol.reference.calendar import TradingCalendar
from prophetovol.runs.config import RunConfig

_SHOWN_DATES = 10


class PreflightIssue(BaseModel):
    """One pre-flight finding (RUN-11)."""

    model_config = ConfigDict(frozen=True)

    severity: Literal["error", "warning"] = Field(description="error blocks the run; warning does not.")
    path: str = Field(description="What the finding is about, for example spec.legs[0].strike, config.end_date or "
                                  "data; empty for the run as a whole.")
    message: str = Field(description="What is wrong and, where possible, how to fix it.")


class PreflightReport(BaseModel):
    """Everything pre-flight found, and the run it would start (RUN-10 to RUN-12)."""

    model_config = ConfigDict(frozen=True)

    spec_id: str = Field(description="The strategy spec's id.")
    spec_version: int | None = Field(default=None, description="The spec version checked; null if it was not found.")
    spec_hash: str | None = Field(default=None, description="The spec version's content hash (VER-2).")
    config: RunConfig | None = Field(default=None, description="The resolved configuration; null if it is invalid.")
    config_hash: str | None = Field(default=None, description="The resolved configuration's hash (VER-3).")
    errors: list[PreflightIssue] = Field(default_factory=list, description="Findings that block the run.")
    warnings: list[PreflightIssue] = Field(default_factory=list, description="Findings that do not block the run.")
    schedule: StepSchedule | None = Field(default=None, description="The run's steps and skipped days; null when "
                                                                    "there are errors.")
    data_versions: list[DataVersionRecord] = Field(
        default_factory=list,
        description="The data version each step will read, in step order: the versions active at pre-flight "
                    "(decision 30). Empty when there are errors.")

    @property
    def ok(self) -> bool:
        """Whether the run can start.

        :returns: True when there are no errors.
        """
        return not self.errors


class PreflightFailed(ValidationFailed):
    """Pre-flight found errors; carries the whole report, warnings included.

    :param report: The report, with at least one error.
    """

    def __init__(self, report: PreflightReport) -> None:
        self.report = report
        super().__init__([ValidationIssue(e.path, e.message) for e in report.errors])


def format_dates(days: list[date]) -> str:
    """A list of dates for a message, shortened when long.

    :param days: The dates, in order.
    :returns: For example ``2024-05-10, 2024-05-13 and 3 more``.
    """
    shown = ", ".join(d.isoformat() for d in days[:_SHOWN_DATES])
    return shown + (f" and {len(days) - _SHOWN_DATES} more" if len(days) > _SHOWN_DATES else "")


def check_data(config: RunConfig, calendar: TradingCalendar, active: list[DataVersionRecord],
               import_sources: Mapping[str, str]) -> tuple[StepSchedule | None, list[DataVersionRecord],
                                                           list[PreflightIssue], list[PreflightIssue]]:
    """Check the run's data and fix its step schedule (RUN-10, RUN-11).

    :param config: The resolved configuration.
    :param calendar: The trading calendar (REF-10).
    :param active: The underlying's active data versions.
    :param import_sources: The data source of each import that supplied an active version in the range.
    :returns: The schedule and the version each step reads (None and empty when there are errors), the errors,
        and the warnings.
    """
    errors: list[PreflightIssue] = []
    warnings: list[PreflightIssue] = []

    def error(path: str, message: str) -> None:
        """Record an error.

        :param path: What it is about.
        :param message: The message.
        """
        errors.append(PreflightIssue(severity="error", path=path, message=message))

    def warning(path: str, message: str) -> None:
        """Record a warning.

        :param path: What it is about.
        :param message: The message.
        """
        warnings.append(PreflightIssue(severity="warning", path=path, message=message))

    missing_columns = sorted(set(ENGINE_COLUMNS) - set(MARKET_COLUMNS))
    if missing_columns:
        error("data", f"market snapshots lack columns the engine reads: {', '.join(missing_columns)}")
    try:
        sessions = calendar.sessions_in_range(config.start_date, config.end_date)
    except ConfigurationError as exc:
        error("config", str(exc))
        return None, [], errors, warnings
    if not sessions:
        error("config", f"no trading day between {config.start_date} and {config.end_date}")
        return None, [], errors, warnings

    in_range = [v for v in active if config.start_date <= v.as_of_date <= config.end_date]
    by_day = {v.as_of_date: v for v in in_range}
    for import_id in sorted({v.import_id for v in in_range}):
        source = import_sources.get(import_id)
        if source != config.data_source:
            error("data", f"import {import_id} comes from data source {source}, not the configuration's "
                          f"{config.data_source}")
    empty = [d for d in sessions if d in by_day and by_day[d].contracts == 0]
    if empty:
        error("data", f"{len(empty)} snapshot(s) have no contracts: {format_dates(empty)}")
    extra = sorted(d for d in by_day if d not in set(sessions))
    if extra:
        warning("data", f"{len(extra)} non-trading date(s) have active data and are ignored: {format_dates(extra)}")
    missing = [d for d in sessions if d not in by_day]
    covered = [d for d in sessions if d in by_day]
    if missing and not config.allow_missing_days:
        error("data", f"{len(missing)} trading day(s) have no active snapshot for {config.underlying}: "
                      f"{format_dates(missing)}. Import them, or set allow_missing_days to skip them.")
    elif missing:
        warning("data", f"skipping {len(missing)} trading day(s) without data: {format_dates(missing)}; the next "
                        "step after each is flagged missing_day_before.")
        for day in missing:
            warning("data", f"{day} is skipped: PM-settled contracts settling on it are closed at the step before "
                            "(SPEC-55).")
    if not covered:
        error("data", f"no trading day between {config.start_date} and {config.end_date} has an active snapshot "
                      f"for {config.underlying}")
    if errors:
        return None, [], errors, warnings

    schedule, versions = build_schedule(sessions, by_day)
    return schedule, versions, errors, warnings


def build_schedule(sessions: list[date], by_day: Mapping[date, DataVersionRecord]
                   ) -> tuple[StepSchedule, list[DataVersionRecord]]:
    """The step schedule of a run: one step per trading day with a data version, the others skipped (RUN-11).

    Pre-flight builds it, and a run job rebuilds the same schedule from the versions it recorded.

    :param sessions: The trading days in the run's range, in order.
    :param by_day: The data version of each covered day.
    :returns: The schedule, and the version each step reads, in step order.
    """
    steps: list[Step] = []
    skipped: list[date] = []
    versions: list[DataVersionRecord] = []
    for day in sessions:
        if day not in by_day:
            skipped.append(day)
            continue
        steps.append(Step(seq=len(steps) + 1, day=day, as_of=by_day[day].as_of, after_missing_days=skipped))
        versions.append(by_day[day])
        skipped = []
    return StepSchedule(steps=steps, missing_days=[d for d in sessions if d not in by_day]), versions
