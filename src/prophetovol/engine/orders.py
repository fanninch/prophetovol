"""What the book is asked to trade (ENG-1 steps 6 to 8).

Opening a structure is one :class:`OpenLeg` per leg, executed together or not at all; closing names
the structure and leg, since the book knows what the leg holds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CONTRACT_FIELDS: tuple[str, ...] = (
    "osi_symbol", "root", "vendor_symbol", "vendor_root", "settlement_style", "expiration", "settlement_date",
    "last_trading_date", "expiry_timestamp", "strike", "option_type")
"""The snapshot fields that identify and describe a contract in position snapshots (RES-1)."""


@dataclass(frozen=True)
class OpenLeg:
    """One leg of an opening order.

    :param leg_id: The spec leg.
    :param contract: The contract's snapshot row at the step (at least :data:`CONTRACT_FIELDS`).
    :param quantity: Signed contracts to open: positive long, negative short (CONV-8).
    """

    leg_id: str
    contract: dict[str, Any]
    quantity: float

    @property
    def osi_symbol(self) -> str:
        """The contract's OSI symbol."""
        return self.contract["osi_symbol"]
