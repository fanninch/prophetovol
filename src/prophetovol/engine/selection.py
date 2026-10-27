"""Expiration and strike selectors (SPEC-10 to SPEC-28).

Phase 9 registers every selector with its parameter model, so specs validate (decision 29); each
implementation holds its validated parameters. The selection behavior arrives in plan Phase 11.
"""

from __future__ import annotations

from prophetovol.registry.catalog import EXPIRATION_SELECTORS, STRIKE_SELECTORS
from prophetovol.registry.params.selection import (AtmParams, DeltaParams, ForwardParams, NextAfterLegParams,
                                                   NthExpirationParams, SameAsLegParams, SameStrikeAsParams,
                                                   StrikeOffsetParams, TargetDaysParams, TradingDaysOutParams)


@EXPIRATION_SELECTORS.register(
    "target_days", params=TargetDaysParams, version="1",
    description="Chooses the expiration whose calendar days to expiry (fractional, CONV-1) is nearest days, among "
                "expirations within [min_days, max_days] that pass the filter. Ties go to the later expiration "
                "unless tie_break is earlier. Example: days 45 for a monthly-style strategy; days 0.5 with "
                "max_days 1 for a same-day expiration.")
class TargetDays:
    """The ``target_days`` expiration selector (SPEC-10).

    :param params: Its validated parameters.
    """

    def __init__(self, params: TargetDaysParams) -> None:
        self.params = params


@EXPIRATION_SELECTORS.register(
    "trading_days_out", params=TradingDaysOutParams, version="1",
    description="Chooses the expiration whose trading days to expiry (CONV-2) equals n, or the nearest within "
                "tolerance trading days, among expirations that pass the filter. Example: n 1 with settlement_styles "
                "[PM] for the next trading day's PM-settled expiration.")
class TradingDaysOut:
    """The ``trading_days_out`` expiration selector (SPEC-11).

    :param params: Its validated parameters.
    """

    def __init__(self, params: TradingDaysOutParams) -> None:
        self.params = params


@EXPIRATION_SELECTORS.register(
    "nth_expiration", params=NthExpirationParams, version="1",
    description="Chooses the n-th eligible expiration after the as-of time, counting only expirations that pass "
                "the filter; n 1 is the next one. Example: n 2 with standard_monthly_only for the second monthly.")
class NthExpiration:
    """The ``nth_expiration`` expiration selector (SPEC-12).

    :param params: Its validated parameters.
    """

    def __init__(self, params: NthExpirationParams) -> None:
        self.params = params


@EXPIRATION_SELECTORS.register(
    "same_as_leg", params=SameAsLegParams, version="1",
    description="Uses the same expiration as the referenced leg, which is selected first (SPEC-3).")
class SameAsLeg:
    """The ``same_as_leg`` expiration selector (SPEC-13).

    :param params: Its validated parameters.
    """

    def __init__(self, params: SameAsLegParams) -> None:
        self.params = params


@EXPIRATION_SELECTORS.register(
    "next_after_leg", params=NextAfterLegParams, version="1",
    description="Chooses the first eligible expiration strictly after the referenced leg's expiration, among "
                "expirations that pass the filter.")
class NextAfterLeg:
    """The ``next_after_leg`` expiration selector (SPEC-13).

    :param params: Its validated parameters.
    """

    def __init__(self, params: NextAfterLegParams) -> None:
        self.params = params


@STRIKE_SELECTORS.register(
    "delta", params=DeltaParams, version="1",
    description="Chooses the strike in the leg's expiration whose absolute delta (the snapshot's, CONV-10) is "
                "nearest target, within tolerance (default 0.05). Targets are absolute: 0.25 is a 25-delta call or "
                "put (CONV-4). Contracts with a null delta are not eligible (SPEC-27).")
class Delta:
    """The ``delta`` strike selector (SPEC-20).

    :param params: Its validated parameters.
    """

    def __init__(self, params: DeltaParams) -> None:
        self.params = params


@STRIKE_SELECTORS.register(
    "atm", params=AtmParams, version="1",
    description="Chooses the at-the-money strike: the 50-delta option of the leg's own type (CONV-5), as delta "
                "with target 0.50. The strike nearest the forward is the separate forward selector.")
class Atm:
    """The ``atm`` strike selector (SPEC-21).

    :param params: Its validated parameters.
    """

    def __init__(self, params: AtmParams) -> None:
        self.params = params


@STRIKE_SELECTORS.register(
    "forward", params=ForwardParams, version="1",
    description="Chooses the strike nearest the series forward (DATA-14), within tolerance_points; by default the "
                "usual strike spacing around the forward in that expiration.")
class Forward:
    """The ``forward`` strike selector (SPEC-22).

    :param params: Its validated parameters.
    """

    def __init__(self, params: ForwardParams) -> None:
        self.params = params


@STRIKE_SELECTORS.register(
    "same_strike_as", params=SameStrikeAsParams, version="1",
    description="Uses the referenced leg's strike, which must be listed in this leg's expiration (within "
                "tolerance_points, default 0: exactly the same strike).")
class SameStrikeAs:
    """The ``same_strike_as`` strike selector (SPEC-23).

    :param params: Its validated parameters.
    """

    def __init__(self, params: SameStrikeAsParams) -> None:
        self.params = params


@STRIKE_SELECTORS.register(
    "strike_offset", params=StrikeOffsetParams, version="1",
    description="Chooses the listed strike nearest the referenced leg's strike plus an offset in points or percent, "
                "within tolerance_points; by default the usual strike spacing around the offset strike.")
class StrikeOffset:
    """The ``strike_offset`` strike selector (SPEC-24).

    :param params: Its validated parameters.
    """

    def __init__(self, params: StrikeOffsetParams) -> None:
        self.params = params
