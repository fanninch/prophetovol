"""The step schedule a run follows, fixed by pre-flight (RUN-11, plan §4.7).

A :class:`StepSchedule` lists the run's steps (one per trading day with data in Phase 1) and the
trading days it skips. It answers what SPEC-55 needs, whether a date has a step and the last step
before a date, without reading any market data.
"""

from __future__ import annotations

import bisect
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


class Step(BaseModel):
    """One step of a run (TIME-1)."""

    model_config = ConfigDict(frozen=True)

    seq: int = Field(ge=1, description="The step's number, from 1.")
    day: date = Field(description="The trading day of the step.")
    as_of: datetime = Field(description="The step's as-of instant (UTC): the snapshot time of the data source on that "
                                        "day, as stored with the market snapshot.")
    after_missing_days: list[date] = Field(
        default_factory=list,
        description="Trading days skipped just before this step (allow_missing_days); its snapshots are flagged "
                    "missing_day_before.")


class StepSchedule(BaseModel):
    """The steps of a run and the trading days it skips (RUN-11)."""

    model_config = ConfigDict(frozen=True)

    steps: list[Step] = Field(description="The steps, in order.")
    missing_days: list[date] = Field(default_factory=list,
                                     description="Trading days in the range without an active snapshot, skipped.")

    _days: list[date] = PrivateAttr(default_factory=list)

    def model_post_init(self, context: object) -> None:
        """Index the steps by day for the lookups.

        :param context: Pydantic's validation context (unused).
        """
        self._days = [s.day for s in self.steps]

    def step_on(self, day: date) -> Step | None:
        """The step on a date.

        :param day: The date.
        :returns: The step, or None when the date has no step.
        """
        i = bisect.bisect_left(self._days, day)
        return self.steps[i] if i < len(self._days) and self._days[i] == day else None

    def has_step(self, day: date) -> bool:
        """Whether a date has a step.

        :param day: The date.
        :returns: True when the run steps on it.
        """
        return self.step_on(day) is not None

    def last_step_before(self, day: date) -> Step | None:
        """The last step strictly before a date (SPEC-55: where a PM leg settling on a skipped day is closed).

        :param day: The date.
        :returns: The step, or None when no step precedes it.
        """
        i = bisect.bisect_left(self._days, day)
        return self.steps[i - 1] if i > 0 else None

    def is_missing(self, day: date) -> bool:
        """Whether a date is a skipped trading day.

        :param day: The date.
        :returns: True when the run skips it for lack of data.
        """
        i = bisect.bisect_left(self.missing_days, day)
        return i < len(self.missing_days) and self.missing_days[i] == day
