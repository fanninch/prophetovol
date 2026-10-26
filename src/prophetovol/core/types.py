"""Small enumerations used across the package."""

from __future__ import annotations

from enum import StrEnum


class OptionType(StrEnum):
    """Call or put."""

    CALL = "call"
    PUT = "put"


class SettlementStyle(StrEnum):
    """How a contract settles: on the special opening value (AM) or on the close (PM)."""

    AM = "AM"
    PM = "PM"


class Frequency(StrEnum):
    """How often a run steps (TIME-1). Phase 1 supports end of day only."""

    END_OF_DAY = "end_of_day"
