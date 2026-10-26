"""Underlying and data-source configurations (REF-1, REF-5).

Both are versioned definitions in the catalog (REF-2); the package ships defaults as YAML
(``reference/defaults``), which seed the catalog as version 1.
"""

from __future__ import annotations

from datetime import date, time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from prophetovol.core.errors import ConfigurationError
from prophetovol.core.types import Frequency, SettlementStyle


def _check_timezone(value: str) -> str:
    """Reject time zones the time zone database does not know.

    :param value: The time zone name.
    :returns: The name, unchanged.
    """
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown time zone {value!r}") from exc
    return value


class RootConfig(BaseModel):
    """How one vendor option root settles and which normalized root it maps to."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    settlement_style: SettlementStyle = Field(
        description="AM: settles on the special opening value at the AM expiry time. "
                    "PM: settles on the index close at the PM expiry time.",
    )
    normalized_root: str = Field(
        min_length=1,
        description="The root strategies and results use for this vendor root: for SPX, SPX for "
                    "AM-settled roots and SPXW for PM-settled roots, in every year.",
    )
    note: str = Field(default="", description="What the root is and when it was listed, for people.")


class Underlying(BaseModel):
    """An index with its contract terms, expiry times and option roots (REF-1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(min_length=1, description="The underlying's symbol in the vendor files, for example SPX.")
    description: str = Field(default="", description="A short description for people.")
    multiplier: float = Field(gt=0, description="Contract multiplier: index points to dollars (100 for SPX).")
    exercise_style: Literal["european"] = Field(
        description="Exercise style. Phase 1 supports European options only.",
    )
    timezone: str = Field(description="The exchange's IANA time zone, for example America/New_York.")
    expiry_times: dict[SettlementStyle, time] = Field(
        description="Exchange-local expiry time per settlement style (CONV-3): 09:30 for AM and 16:00 for PM for SPX.",
    )
    roots: dict[str, RootConfig] = Field(
        description="Every vendor option root of this underlying, keyed by the root as parsed from the "
                    "vendor symbol (DATA-13). A root not listed here fails ingest.",
    )

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        """Reject time zones the time zone database does not know.

        :param value: The time zone name.
        :returns: The name, unchanged.
        """
        return _check_timezone(value)

    @model_validator(mode="after")
    def _consistent(self) -> Underlying:
        """Check expiry times cover both styles and normalized roots are consistent.

        :returns: The validated model.
        """
        missing = set(SettlementStyle) - set(self.expiry_times)
        if missing:
            raise ValueError(f"expiry_times is missing {sorted(missing)}")
        if not self.roots:
            raise ValueError("at least one root is required")
        for name, root in self.roots.items():
            target = self.roots.get(root.normalized_root)
            if target is None:
                raise ValueError(f"root {name}: normalized root {root.normalized_root!r} is not itself a listed root")
            if target.normalized_root != root.normalized_root:
                raise ValueError(f"root {root.normalized_root} must normalize to itself")
            if target.settlement_style != root.settlement_style:
                raise ValueError(f"root {name} ({root.settlement_style}) normalizes to {root.normalized_root} "
                                 f"({target.settlement_style}): settlement styles must match")
        return self

    def root(self, vendor_root: str) -> RootConfig:
        """Look up a vendor root.

        :param vendor_root: The root parsed from a vendor symbol.
        :returns: Its configuration.
        :raises ConfigurationError: If the root is not configured (an ingest error, DATA-20).
        """
        try:
            return self.roots[vendor_root]
        except KeyError:
            raise ConfigurationError(f"unknown option root {vendor_root!r} for {self.symbol}") from None

    def normalized_roots(self) -> list[str]:
        """The roots strategies select from (SPEC-2), in alphabetical order.

        :returns: The distinct normalized roots.
        """
        return sorted({r.normalized_root for r in self.roots.values()})

    def expiry_time(self, settlement_style: SettlementStyle | str) -> time:
        """The exchange-local expiry time of a settlement style.

        :param settlement_style: ``AM`` or ``PM``.
        :returns: The expiry time.
        """
        return self.expiry_times[SettlementStyle(settlement_style)]


class DataSource(BaseModel):
    """A vendor data format with its snapshot timing and conventions (REF-5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1, description="The data source's id, for example ivolatility_eod.")
    description: str = Field(default="", description="A short description for people.")
    frequency: Frequency = Field(description="How often the source has snapshots. Phase 1: end_of_day.")
    timezone: str = Field(description="IANA time zone of the snapshot times.")
    option_snapshot_time: time = Field(
        description="Exchange-local time of the option quotes, IV, greeks and forward (16:15 for ivolatility_eod).",
    )
    index_snapshot_time: time = Field(
        description="Exchange-local time of the index level, the adjusted close (16:00 for ivolatility_eod).",
    )
    time_to_expiry_convention: Literal["act_365_exchange_clock_to_minute"] = Field(
        description="How the source measures time to expiry. act_365_exchange_clock_to_minute equals CONV-1, "
                    "so the source's implied vols are used without rescaling (DATA-15).",
    )
    per_series_forward_from: date | None = Field(
        default=None,
        description="First date on which the vendor's forward column is a per-series forward. Before it, "
                    "the column is one underlying price per date and the forward is derived from put-call "
                    "parity (DATA-14). Null if the vendor always supplies per-series forwards.",
    )
    internal_greeks_from: date | None = Field(
        default=None,
        description="First date from which the source's greeks follow the internal conventions (CONV-10) and are "
                    "used as they are. Before it, ingest recomputes them with Black-76 (DATA-13, DATA-15). Null if the "
                    "source's greeks always follow them.",
    )
    parity_strikes: int = Field(
        default=6, ge=2,
        description="Number of strikes nearest the money used to fit a parity forward per expiration (DATA-14).",
    )

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        """Reject time zones the time zone database does not know.

        :param value: The time zone name.
        :returns: The name, unchanged.
        """
        return _check_timezone(value)
