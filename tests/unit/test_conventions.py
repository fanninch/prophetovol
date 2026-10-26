"""The conventions module (requirements §5.4, DOC-3)."""

import pytest

from prophetovol.core.conventions import (CONVENTIONS, MINUTES_PER_YEAR, dollar_delta, dollar_gamma_1pct,
                                          dollar_theta, dollar_vega)


def test_all_nine_conventions_in_order_with_text():
    assert [c.id for c in CONVENTIONS] == [f"CONV-{i}" for i in range(1, 10)]
    assert all(c.title and len(c.statement) > 40 for c in CONVENTIONS)


def test_conv_1_states_the_exchange_clock():
    assert "exchange" in CONVENTIONS[0].statement and "daylight-saving" in CONVENTIONS[0].statement


def test_minutes_per_year():
    assert MINUTES_PER_YEAR == 525_600


def test_dollar_greeks_for_a_short_call():
    # 10 short contracts, delta 0.30, gamma 0.002, vega 5, theta -1.2, S = 5000, m = 100
    assert dollar_delta(0.30, -10, 100, 5000) == pytest.approx(-1_500_000)
    # a 1% move (50 points) changes delta by 0.002 * 50 = 0.1 per contract: 0.1 * 10 * 100 * 5000 = 500,000
    assert dollar_gamma_1pct(0.002, -10, 100, 5000) == pytest.approx(-500_000)
    assert dollar_vega(5.0, -10, 100) == pytest.approx(-5_000)
    assert dollar_theta(-1.2, -10, 100) == pytest.approx(1_200)
