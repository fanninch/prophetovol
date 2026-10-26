"""ProphetoVol's internal conventions, which apply everywhere: specs, results and documentation (§5.4).

They are defined independently of any data vendor; each data source's adapter converts into them
(DATA-15).

The published conventions document is generated from :data:`CONVENTIONS` (DOC-3), so the text
here is the single statement of each convention. The numeric constants and the dollar-greek
formulas are the code every other module uses.
"""

from __future__ import annotations

from dataclasses import dataclass

DAYS_PER_YEAR = 365
"""Calendar days in the year fraction of time to expiry (CONV-1)."""

MINUTES_PER_YEAR = DAYS_PER_YEAR * 24 * 60
"""Minutes in 365 days: time to expiry in minutes divided by this is the year fraction (CONV-1)."""


@dataclass(frozen=True)
class Convention:
    """One convention, as published.

    :param id: The requirement id, for example ``CONV-1``.
    :param title: A short name.
    :param statement: The convention in full, written for a reader with no other context.
    """

    id: str
    title: str
    statement: str


CONVENTIONS: tuple[Convention, ...] = (
    Convention(
        "CONV-1", "Time to expiry",
        "Time to expiry is a year fraction in calendar time, measured on the exchange's clock: "
        "(expiry − as-of) in whole minutes, divided by the minutes in 365 days, where both are "
        "exchange-local date-times without time zone, so a daylight-saving change between them is "
        "ignored. It agrees with the first data source (ivolatility), whose implied vols therefore need no "
        "conversion; a source measuring time differently has its implied vols rescaled by its adapter. It is "
        "also shown as fractional calendar days to "
        "expiry (time to expiry × 365): a one-day PM-settled weekly at the 16:15 snapshot shows 0.99 days.",
    ),
    Convention(
        "CONV-2", "Trading days to expiry",
        "Trading days to expiry is the number of trading days after the as-of date, up to and "
        "including the settlement date. It is used where a rule is stated in trading days.",
    ),
    Convention(
        "CONV-3", "Settlement date, expiry and last trading day",
        "The settlement date is the last trading day on or before the expiration date (it differs "
        "from the expiration date for the Saturday-dated SPX monthlies before 2015, which settled on "
        "the Friday before). The expiry is the settlement date at 09:30 ET for AM-settled roots and "
        "16:00 ET for PM-settled roots. The last trading day is the trading day before the settlement "
        "date for AM-settled roots (normally the Thursday) and the settlement date for PM-settled roots.",
    ),
    Convention(
        "CONV-4", "Delta targets are absolute values",
        "A 25-delta put is a put whose delta is −0.25; a spec writes target: 0.25 for calls and puts alike.",
    ),
    Convention(
        "CONV-5", "At the money",
        "At the money means the 50-delta option of the leg's own type (call or put), not the strike "
        "nearest to spot. The strike nearest the series forward is a separate selector.",
    ),
    Convention(
        "CONV-6", "Trades execute at the triggering step",
        "Trades execute at the step at which the triggering condition is observed. For end-of-day "
        "data, that is the close.",
    ),
    Convention(
        "CONV-7", "Dollar greeks",
        "With q the signed quantity in contracts, m the multiplier and S the index level: dollar "
        "delta = Δ·q·m·S (equivalent index exposure); dollar gamma = Γ·q·m·S²·0.01 (change in dollar "
        "delta for a 1% index move); dollar vega = vega·q·m (per volatility point, CONV-10); dollar theta = "
        "θ·q·m (per calendar day, CONV-10).",
    ),
    Convention(
        "CONV-8", "Signs",
        "A positive quantity is long; a positive cash flow is cash received.",
    ),
    Convention(
        "CONV-9", "A roll re-establishes the structure",
        "Unless the spec says otherwise, a roll closes the structure and re-establishes it using the "
        "original selection rules.",
    ),
    Convention(
        "CONV-10", "Prices, implied vol and greeks",
        "Per contract: prices in index points per unit of the underlying (dollars are price × quantity × "
        "multiplier); implied volatility as a decimal, consistent with CONV-1's time to expiry; one forward per "
        "expiration and date; delta is the undiscounted Black-76 forward delta, N(d1) for a call and N(d1) − 1 "
        "for a put (for a call and a put at the same strike and implied vol, call delta − put delta = 1); gamma is per "
        "point of the forward; vega is per volatility point; "
        "theta is per calendar day.",
    ),
)
"""Every convention, in requirement order."""


def dollar_delta(delta: float, quantity: float, multiplier: float, index_level: float) -> float:
    """Dollar delta, the equivalent index exposure (CONV-7).

    :param delta: Per-contract delta.
    :param quantity: Signed quantity in contracts (positive is long, CONV-8).
    :param multiplier: Contract multiplier.
    :param index_level: Index level S.
    :returns: Δ·q·m·S.
    """
    return delta * quantity * multiplier * index_level


def dollar_gamma_1pct(gamma: float, quantity: float, multiplier: float, index_level: float) -> float:
    """Dollar gamma, the change in dollar delta for a 1% index move (CONV-7).

    :param gamma: Per-contract gamma.
    :param quantity: Signed quantity in contracts.
    :param multiplier: Contract multiplier.
    :param index_level: Index level S.
    :returns: Γ·q·m·S²·0.01.
    """
    return gamma * quantity * multiplier * index_level * index_level * 0.01


def dollar_vega(vega: float, quantity: float, multiplier: float) -> float:
    """Dollar vega per volatility point (CONV-7, CONV-10).

    :param vega: Per-contract vega, per volatility point.
    :param quantity: Signed quantity in contracts.
    :param multiplier: Contract multiplier.
    :returns: vega·q·m.
    """
    return vega * quantity * multiplier


def dollar_theta(theta: float, quantity: float, multiplier: float) -> float:
    """Dollar theta per calendar day (CONV-7, CONV-10).

    :param theta: Per-contract theta, per calendar day.
    :param quantity: Signed quantity in contracts.
    :param multiplier: Contract multiplier.
    :returns: θ·q·m.
    """
    return theta * quantity * multiplier
