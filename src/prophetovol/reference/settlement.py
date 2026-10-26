"""Settlement sources: how a contract held to its expiry is settled (REF-20, REF-21)."""

from __future__ import annotations

from typing import Protocol

from prophetovol.core.errors import ConfigurationError
from prophetovol.core.types import OptionType, SettlementStyle
from prophetovol.registry.catalog import SETTLEMENT_SOURCES
from prophetovol.registry.params.settlement import PmIndexCloseParams


class SettlementSource(Protocol):
    """A way of valuing contracts of one settlement style at expiry."""

    settlement_style: SettlementStyle
    """The settlement style this source settles."""

    def settlement_value(self, option_type: OptionType, strike: float, index_level: float) -> float:
        """Return the per-unit settlement value of a contract (before the multiplier).

        :param option_type: Call or put.
        :param strike: The contract's strike.
        :param index_level: The settlement index level the source supplies.
        """


def intrinsic_value(option_type: OptionType | str, strike: float, index_level: float) -> float:
    """The intrinsic value of a European option against an index level.

    :param option_type: Call or put.
    :param strike: The strike.
    :param index_level: The index level.
    :returns: ``max(S − K, 0)`` for a call, ``max(K − S, 0)`` for a put.
    """
    if OptionType(option_type) is OptionType.CALL:
        return max(index_level - strike, 0.0)
    return max(strike - index_level, 0.0)


@SETTLEMENT_SOURCES.register(
    "pm_index_close",
    description="Settles PM-settled contracts at intrinsic value against the index close on the settlement "
                "date (the vendor's adjusted close on that date). Settlement is a cash flow with no fill-model "
                "cost (SPEC-50).",
    params=PmIndexCloseParams,
    version="1",
)
class PmIndexClose:
    """Settle PM-settled contracts against the index close on the settlement date (REF-20).

    :param params: Its parameters (none).
    """

    settlement_style = SettlementStyle.PM

    def __init__(self, params: PmIndexCloseParams | None = None) -> None:
        self.params = params or PmIndexCloseParams()

    def settlement_value(self, option_type: OptionType, strike: float, index_level: float) -> float:
        """Return the intrinsic value against the index close.

        :param option_type: Call or put.
        :param strike: The contract's strike.
        :param index_level: The index close on the settlement date.
        :returns: The per-unit settlement value.
        """
        return intrinsic_value(option_type, strike, index_level)


def settlement_source_for(settlement_style: SettlementStyle | str) -> SettlementSource:
    """The settlement source for a settlement style.

    :param settlement_style: ``AM`` or ``PM``.
    :returns: A source instance.
    :raises ConfigurationError: For AM-settled contracts, for which no source exists in Phase 1 (REF-21).
    """
    style = SettlementStyle(settlement_style)
    for name in SETTLEMENT_SOURCES.names():
        target = SETTLEMENT_SOURCES.get(name).target
        if target.settlement_style is style:
            return target()
    raise ConfigurationError(
        f"no settlement source for {style}-settled contracts: the vendor data has no AM settlement value "
        "(SET), so AM-settled contracts are closed on their last trading day (REF-21, SPEC-51)")
