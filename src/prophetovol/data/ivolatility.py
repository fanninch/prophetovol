"""The ivolatility end-of-day option file format (DATA-1, DATA-2, Appendix A).

Ingest reads this format; the synthetic data generator writes it.
"""

from __future__ import annotations

from datetime import date

from prophetovol.core.types import OptionType

COLUMNS: tuple[str, ...] = (
    "symbol", "exchange", "date", "adjusted close", "option symbol", "expiration", "strike", "call/put", "style",
    "ask", "bid", "mean price", "iv", "volume", "open interest", "stock price for iv", "*", "delta", "vega",
    "gamma", "theta", "rho",
)
"""The 22 columns, in file order (DATA-1)."""

DATE_FORMAT = "%m/%d/%Y"
"""The format of ``date`` and ``expiration`` (DATA-2)."""

OSI_ROOT_WIDTH = 6
"""OSI symbols pad the root to six characters."""

OPRA_CODE_LENGTH = 5
"""Older five-character OPRA codes: a three-character root, a month code and a strike code."""


def format_date(day: date) -> str:
    """Format a date as the vendor does.

    :param day: The date.
    :returns: ``MM/DD/YYYY``.
    """
    return day.strftime(DATE_FORMAT)


def osi_symbol(root: str, expiration: date, option_type: OptionType | str, strike: float) -> str:
    """Build an OSI option symbol (DATA-2), as used by the vendor from Feb 12, 2010 and for ``osi_symbol``.

    :param root: The option root, at most six characters.
    :param expiration: The expiration date as listed.
    :param option_type: Call or put.
    :param strike: The strike.
    :returns: For example ``SPXW  240830C01400000``: root padded to six, ``YYMMDD``, ``C``/``P``, strike × 1000
        in eight digits.
    :raises ValueError: If the root is too long or the strike does not fit.
    """
    if not 1 <= len(root) <= OSI_ROOT_WIDTH:
        raise ValueError(f"OSI roots have 1 to {OSI_ROOT_WIDTH} characters: {root!r}")
    millis = round(strike * 1000)
    if not 0 < millis < 10**8:
        raise ValueError(f"strike {strike} does not fit an OSI symbol")
    letter = "C" if OptionType(option_type) is OptionType.CALL else "P"
    return f"{root:<{OSI_ROOT_WIDTH}}{expiration:%y%m%d}{letter}{millis:08d}"


def vendor_root(option_symbol: str) -> str:
    """The root of a vendor option symbol in either format (DATA-13).

    :param option_symbol: A five-character OPRA code or an OSI symbol.
    :returns: The first three characters of an OPRA code, or the characters before the date of an OSI
        symbol, trimmed.
    """
    if len(option_symbol) == OPRA_CODE_LENGTH:
        return option_symbol[:3]
    return option_symbol[:OSI_ROOT_WIDTH].strip()
