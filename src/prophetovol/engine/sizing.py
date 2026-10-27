"""Sizing methods (SPEC-70 to SPEC-73).

Phase 9 registers every method with its parameter model, so specs validate (decision 29); each
implementation holds its validated parameters. The sizing behavior arrives in plan Phase 12.
"""

from __future__ import annotations

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
