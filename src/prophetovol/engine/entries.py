"""Entry schedules (SPEC-30 to SPEC-35).

Phase 9 registers every schedule with its parameter model, so specs validate (decision 29); each
implementation holds its validated parameters. The scheduling behavior arrives in plan Phase 11.
"""

from __future__ import annotations

from prophetovol.registry.catalog import ENTRY_SCHEDULES
from prophetovol.registry.params.schedules import (EveryNTradingDaysParams, OnceParams, WeekdaysParams,
                                                   WhenFlatParams)


@ENTRY_SCHEDULES.register(
    "once", params=OnceParams, version="1",
    description="Opens one structure at the first step of the run. If selection fails there, it is retried at the "
                "next step until one opens.")
class Once:
    """The ``once`` entry schedule (SPEC-30).

    :param params: Its validated parameters.
    """

    def __init__(self, params: OnceParams) -> None:
        self.params = params


@ENTRY_SCHEDULES.register(
    "when_flat", params=WhenFlatParams, version="1",
    description="Opens a structure at any step when fewer than max_open structures of this spec are open (by default "
                "when none is), waiting cooldown_trading_days after a close by a close action or by expiry. A roll "
                "re-establishes the structure immediately, without the cooldown.")
class WhenFlat:
    """The ``when_flat`` entry schedule (SPEC-31).

    :param params: Its validated parameters.
    """

    def __init__(self, params: WhenFlatParams) -> None:
        self.params = params


@ENTRY_SCHEDULES.register(
    "every_n_trading_days", params=EveryNTradingDaysParams, version="1",
    description="Opens a structure every n trading days from the run's first step, counted on the trading calendar, "
                "while fewer than max_open structures of this spec are open.")
class EveryNTradingDays:
    """The ``every_n_trading_days`` entry schedule (SPEC-32).

    :param params: Its validated parameters.
    """

    def __init__(self, params: EveryNTradingDaysParams) -> None:
        self.params = params


@ENTRY_SCHEDULES.register(
    "weekdays", params=WeekdaysParams, version="1",
    description="Opens a structure on the listed weekdays while fewer than max_open structures of this spec are "
                "open. When a listed day is not a trading day, holiday_shift skips it (default) or moves the entry "
                "to the next trading day.")
class Weekdays:
    """The ``weekdays`` entry schedule (SPEC-33).

    :param params: Its validated parameters.
    """

    def __init__(self, params: WeekdaysParams) -> None:
        self.params = params
