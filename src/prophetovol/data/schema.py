"""The normalized market snapshot (DATA-13, DATA-15, Appendix A): the columns every data-source
adapter writes and the engine reads.

Columns are in the internal conventions (§5.4, CONV-10) unless they start with ``vendor_``, which
keep the source's values as given for traceability.
"""

from __future__ import annotations

from enum import StrEnum

import pyarrow as pa


class ForwardSource(StrEnum):
    """Where a row's ``forward`` came from (DATA-14)."""

    VENDOR = "vendor"
    PARITY = "parity"
    VENDOR_SINGLE_PRICE = "vendor_single_price"


class GreeksSource(StrEnum):
    """Where a row's internal greeks came from (DATA-13, DATA-15)."""

    VENDOR = "vendor"
    RECOMPUTED = "recomputed"


class VendorMethodology(StrEnum):
    """The vendor period a row belongs to (DATA-13)."""

    SINGLE_PRICE = "single_price"
    PER_SERIES_FORWARD = "per_series_forward"


_TS = pa.timestamp("us", tz="UTC")
_LOCAL = pa.timestamp("us")

MARKET_SCHEMA = pa.schema([
    ("underlying", pa.string()),
    ("exchange", pa.string()),
    ("as_of_date", pa.date32()),
    ("as_of", _TS),
    ("as_of_local", _LOCAL),
    ("index_as_of", _TS),
    ("index_level", pa.float64()),
    ("vendor_symbol", pa.string()),
    ("vendor_root", pa.string()),
    ("root", pa.string()),
    ("settlement_style", pa.string()),
    ("osi_symbol", pa.string()),
    ("expiration", pa.date32()),
    ("settlement_date", pa.date32()),
    ("expiry_timestamp", _TS),
    ("expiry_local", _LOCAL),
    ("last_trading_date", pa.date32()),
    ("time_to_expiry_years", pa.float64()),
    ("days_to_expiry", pa.float64()),
    ("trading_days_to_expiry", pa.int32()),
    ("strike", pa.float64()),
    ("option_type", pa.string()),
    ("exercise_style", pa.string()),
    ("bid", pa.float64()),
    ("ask", pa.float64()),
    ("vendor_mid", pa.float64()),
    ("volume", pa.int64()),
    ("open_interest", pa.int64()),
    ("vendor_flag", pa.bool_()),
    ("vendor_iv", pa.float64()),
    ("iv", pa.float64()),
    ("vendor_forward", pa.float64()),
    ("forward", pa.float64()),
    ("forward_source", pa.string()),
    ("parity_forward", pa.float64()),
    ("parity_discount", pa.float64()),
    ("parity_strikes", pa.int32()),
    ("vendor_methodology", pa.string()),
    ("vendor_delta", pa.float64()),
    ("vendor_gamma", pa.float64()),
    ("vendor_vega", pa.float64()),
    ("vendor_theta", pa.float64()),
    ("vendor_rho", pa.float64()),
    ("delta", pa.float64()),
    ("gamma", pa.float64()),
    ("vega", pa.float64()),
    ("theta", pa.float64()),
    ("greeks_source", pa.string()),
    ("import_id", pa.string()),
])
"""The columns of a market snapshot, in file order."""

MARKET_COLUMNS: tuple[str, ...] = tuple(MARKET_SCHEMA.names)
"""The column names, in file order."""

SORT_KEYS: tuple[str, ...] = ("as_of", "root", "expiration", "option_type", "strike")
"""Rows are stored in this order within a partition (plan §4.2)."""
