"""Quotes and marks (ENG-20 to ENG-25).

A quote is valid when ``ask > 0``, ``bid ≥ 0`` and ``ask ≥ bid``, and its mid is ``(bid + ask) / 2``
(ENG-20). A position is marked at the mid of its valid quote; otherwise its last valid mark is
carried forward and flagged ``stale_mark`` (ENG-21). The book applies these at every step.
"""

from __future__ import annotations

import math
from typing import Any


def valid_quote(bid: float | None, ask: float | None) -> bool:
    """Whether a quote is valid (ENG-20).

    :param bid: The bid, or None when missing.
    :param ask: The ask, or None when missing.
    :returns: True for ``ask > 0``, ``bid ≥ 0`` and ``ask ≥ bid``.
    """
    if bid is None or ask is None or math.isnan(bid) or math.isnan(ask):
        return False
    return ask > 0 and bid >= 0 and ask >= bid


def mid(bid: float, ask: float) -> float:
    """The mid of a quote.

    :param bid: The bid.
    :param ask: The ask.
    :returns: ``(bid + ask) / 2``.
    """
    return (bid + ask) / 2


def quote_of(row: dict[str, Any] | None) -> tuple[float | None, float | None]:
    """A snapshot row's bid and ask.

    :param row: The contract's row, or None when it is absent from the snapshot.
    :returns: ``(bid, ask)``, None where missing.
    """
    if row is None:
        return None, None
    return row.get("bid"), row.get("ask")
