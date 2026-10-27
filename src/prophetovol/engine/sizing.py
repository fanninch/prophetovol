"""Sizing methods (SPEC-70 to SPEC-73).

A sizing method's :meth:`units` gives an entry's structure units before rounding; :func:`round_units`
applies the run's rounding (SPEC-72). A structure roll re-sizes at the roll step; a leg roll keeps
its leg's quantity (SPEC-73). The hedge is never rounded (SPEC-62).
"""

from __future__ import annotations

import math

from prophetovol.registry.catalog import SIZING_METHODS
from prophetovol.registry.params.sizing import ContractsParams, NotionalParams


@SIZING_METHODS.register(
    "contracts", params=ContractsParams, version="1",
    description="Opens quantity structure units per entry; leg i trades quantity × ratio_i contracts. Units are "
                "rounded as the run configuration says: whole (down; below 1 skips the entry) or fractional.")
class Contracts:
    """The ``contracts`` sizing method (SPEC-70).

    :param params: Its validated parameters.
    """

    def __init__(self, params: ContractsParams) -> None:
        self.params = params

    def units(self, index_level: float, multiplier: float) -> float:
        """Structure units per entry, before rounding.

        :param index_level: The entry step's index level (unused).
        :param multiplier: The contract multiplier (unused).
        :returns: ``quantity``.
        """
        return self.params.quantity


@SIZING_METHODS.register(
    "notional", params=NotionalParams, version="1",
    description="Opens notional / (S × m) structure units per entry, with S the index level at the entry step and m "
                "the multiplier, rounded as the run configuration says.")
class Notional:
    """The ``notional`` sizing method (SPEC-71).

    :param params: Its validated parameters.
    """

    def __init__(self, params: NotionalParams) -> None:
        self.params = params

    def units(self, index_level: float, multiplier: float) -> float:
        """Structure units per entry, before rounding.

        :param index_level: The entry step's index level S.
        :param multiplier: The contract multiplier m.
        :returns: ``notional / (S · m)``.
        """
        return self.params.notional / (index_level * multiplier)


def round_units(units: float, rounding: str) -> float | None:
    """Apply the run's rounding to structure units (SPEC-72).

    :param units: Units before rounding.
    :param rounding: ``whole`` or ``fractional``.
    :returns: Whole units rounded down (None when below one: the entry is skipped), or the units unchanged.
    """
    if rounding == "fractional":
        return units
    whole = float(math.floor(units + 1e-9))
    return whole if whole >= 1 else None
