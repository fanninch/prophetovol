"""Underlyings and data sources (REF-1, REF-5): shipped defaults and validation."""

from datetime import date, time

import pydantic
import pytest

from prophetovol.core.errors import ConfigurationError
from prophetovol.core.types import Frequency, SettlementStyle
from prophetovol.reference.defaults import default_data_sources, default_underlyings
from prophetovol.reference.models import Underlying

# Every vendor root found in the 2007 - Aug 2024 files (Phase 0, plan §15.6) and its settlement style
AM_ROOTS = ["SPX", "SZP", "SXY", "SPT", "SXZ", "SPQ", "SXB", "SXM", "SPZ", "SYG", "SZT", "SPB", "SYU", "SXG",
            "SZJ", "SZV", "SVP", "SYZ", "SPL", "SPV", "SZU", "SZD", "SYV", "SXJ"]
PM_ROOTS = ["SPXW", "SPXPM", "SPXQ", "JXA", "JXB", "JXD", "JXE", "SZQ", "SAQ", "SLQ", "QSE", "SQP", "QZQ",
            "QSZ", "SKQ", "SQG"]


@pytest.fixture(scope="module")
def spx() -> Underlying:
    return default_underlyings()["SPX"]


def test_spx_terms(spx):
    assert spx.multiplier == 100 and spx.exercise_style == "european" and spx.timezone == "America/New_York"
    assert spx.expiry_time("AM") == time(9, 30) and spx.expiry_time(SettlementStyle.PM) == time(16, 0)


def test_every_historical_root_is_configured(spx):
    assert sorted(spx.roots) == sorted(AM_ROOTS + PM_ROOTS)
    for root in AM_ROOTS:
        assert (spx.root(root).settlement_style, spx.root(root).normalized_root) == (SettlementStyle.AM, "SPX")
    for root in PM_ROOTS:
        assert (spx.root(root).settlement_style, spx.root(root).normalized_root) == (SettlementStyle.PM, "SPXW")


def test_normalized_roots_are_today_s_two(spx):
    assert spx.normalized_roots() == ["SPX", "SPXW"]


def test_unknown_root_is_a_configuration_error(spx):
    with pytest.raises(ConfigurationError, match="unknown option root 'XYZ' for SPX"):
        spx.root("XYZ")


def test_ivolatility_data_source():
    src = default_data_sources()["ivolatility_eod"]
    assert src.frequency is Frequency.END_OF_DAY
    assert (src.option_snapshot_time, src.index_snapshot_time) == (time(16, 15), time(16, 0))
    assert src.time_to_expiry_convention == "act_365_exchange_clock_to_minute"
    assert src.per_series_forward_from == date(2018, 6, 25) and src.parity_strikes == 6


def _config(**changes):
    base = {"symbol": "X", "multiplier": 100, "exercise_style": "european", "timezone": "America/New_York",
            "expiry_times": {"AM": "09:30", "PM": "16:00"},
            "roots": {"X": {"settlement_style": "AM", "normalized_root": "X"},
                      "XW": {"settlement_style": "PM", "normalized_root": "XW"}}}
    base.update(changes)
    return base


@pytest.mark.parametrize("changes, message", [
    ({"timezone": "Mars/Olympus"}, "unknown time zone"),
    ({"expiry_times": {"AM": "09:30"}}, "expiry_times is missing"),
    ({"roots": {"X": {"settlement_style": "AM", "normalized_root": "Y"}}}, "is not itself a listed root"),
    ({"roots": {"X": {"settlement_style": "AM", "normalized_root": "X"},
                "OLD": {"settlement_style": "PM", "normalized_root": "X"}}}, "settlement styles must match"),
    ({"exercise_style": "american"}, "european"),
    ({"multiplier": 0}, "greater than 0"),
])
def test_inconsistent_underlyings_are_rejected(changes, message):
    with pytest.raises(pydantic.ValidationError, match=message):
        Underlying.model_validate(_config(**changes))


def test_unknown_keys_are_rejected():
    with pytest.raises(pydantic.ValidationError, match="Extra inputs"):
        Underlying.model_validate(_config(colour="blue"))
