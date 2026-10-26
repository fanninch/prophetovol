"""Black-76 prices and greeks (STR-20) in the vendor's conventions."""

import math

import numpy as np
import pytest
from scipy.special import ndtr

from prophetovol.pricing import black76


def test_at_the_money_closed_form():
    # F = K: call = put = F * (2 N(sigma sqrt(T) / 2) - 1)
    expected = 100 * (2 * ndtr(0.1) - 1)
    assert black76.price(100, 100, 1.0, 0.2, True) == pytest.approx(expected, abs=1e-12)
    assert black76.price(100, 100, 1.0, 0.2, False) == pytest.approx(expected, abs=1e-12)
    assert expected == pytest.approx(7.965567, abs=1e-6)


@pytest.mark.parametrize("f, k, t, vol, disc", [(5000, 4800, 0.1, 0.18, 0.99), (5000, 5300, 0.5, 0.15, 0.98),
                                                 (4000, 4000, 2 / 365, 0.3, 1.0)])
def test_put_call_parity(f, k, t, vol, disc):
    c = black76.price(f, k, t, vol, True, disc)
    p = black76.price(f, k, t, vol, False, disc)
    assert c - p == pytest.approx(disc * (f - k), abs=1e-8)


def test_broadcasting_over_arrays():
    k = np.array([4900.0, 5000.0, 5100.0])
    out = black76.price(5000.0, k, 0.25, 0.2, np.array([True, True, False]))
    assert out.shape == (3,) and out[0] > out[1] > 0 and out[2] > 0


@pytest.mark.parametrize("call", [True, False])
def test_greeks_match_finite_differences(call):
    f, k, t, vol = 5000.0, 5100.0, 30 / 365, 0.17
    g = black76.greeks(f, k, t, vol, call)
    h = 0.01
    delta_fd = (black76.price(f + h, k, t, vol, call) - black76.price(f - h, k, t, vol, call)) / (2 * h)
    gamma_fd = (black76.greeks(f + h, k, t, vol, call).delta - black76.greeks(f - h, k, t, vol, call).delta) / (2 * h)
    vega_fd = (black76.price(f, k, t, vol + 1e-5, call) - black76.price(f, k, t, vol - 1e-5, call)) / 2e-5 * 0.01
    dt = 1e-6
    theta_fd = -(black76.price(f, k, t + dt, vol, call) - black76.price(f, k, t - dt, vol, call)) / (2 * dt) / 365
    assert g.delta == pytest.approx(delta_fd, abs=1e-7)
    assert g.gamma == pytest.approx(gamma_fd, rel=1e-5)
    assert g.vega == pytest.approx(vega_fd, rel=1e-6)
    assert g.theta == pytest.approx(theta_fd, rel=1e-5)


def test_delta_conventions():
    g_call = black76.greeks(5000, 5000, 0.25, 0.2, True)
    g_put = black76.greeks(5000, 5000, 0.25, 0.2, False)
    assert g_call.delta - g_put.delta == pytest.approx(1.0)  # undiscounted, as the vendor from Jun 2018
    d = math.exp(-0.04 * 0.25)
    old_call = black76.greeks(5000, 5000, 0.25, 0.2, True, delta_discount=d)
    old_put = black76.greeks(5000, 5000, 0.25, 0.2, False, delta_discount=d)
    assert old_call.delta - old_put.delta == pytest.approx(d)  # discounted, as before Jun 2018
    assert g_call.gamma == g_put.gamma and g_call.vega == g_put.vega and g_call.theta < 0
