"""Black-76: European option prices and greeks on a forward (STR-20).

All functions take NumPy arrays or scalars and broadcast. ``time`` is time to expiry in years
(CONV-1), ``vol`` the implied volatility as a decimal, ``is_call`` a boolean (array).

The greeks follow the vendor's conventions, confirmed in Phase 0: delta is the undiscounted
forward delta, ``N(d1)`` for a call and ``N(d1) − 1`` for a put, optionally scaled by a discount
factor (the vendor's deltas before Jun 25, 2018 were discounted); gamma is with respect to the
forward; vega is per volatility point (×0.01) and theta per calendar day (÷365), both on the
undiscounted price.
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.special import ndtr

from prophetovol.core.conventions import DAYS_PER_YEAR

_SQRT_2PI = np.sqrt(2.0 * np.pi)


def _pdf(x: NDArray[np.float64]) -> NDArray[np.float64]:
    """The standard normal density.

    :param x: Points.
    :returns: φ(x).
    """
    return np.exp(-0.5 * x * x) / _SQRT_2PI


def d1_d2(forward: ArrayLike, strike: ArrayLike, time: ArrayLike,
          vol: ArrayLike) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """The Black-76 ``d1`` and ``d2``.

    :param forward: Forward F.
    :param strike: Strike K.
    :param time: Time to expiry T in years (positive).
    :param vol: Implied volatility σ (positive).
    :returns: ``d1 = (ln(F/K) + σ²T/2) / (σ√T)`` and ``d2 = d1 − σ√T``.
    """
    f, k, t, s = (np.asarray(a, dtype=float) for a in (forward, strike, time, vol))
    sd = s * np.sqrt(t)
    d1 = (np.log(f / k) + 0.5 * sd * sd) / sd
    return d1, d1 - sd


def price(forward: ArrayLike, strike: ArrayLike, time: ArrayLike, vol: ArrayLike, is_call: ArrayLike,
          discount: ArrayLike = 1.0) -> NDArray[np.float64]:
    """The Black-76 price.

    :param forward: Forward F.
    :param strike: Strike K.
    :param time: Time to expiry T in years (positive).
    :param vol: Implied volatility σ.
    :param is_call: True for calls, False for puts.
    :param discount: Discount factor D = exp(−rT); 1 means no discounting.
    :returns: ``D·[F·N(d1) − K·N(d2)]`` for calls and ``D·[K·N(−d2) − F·N(−d1)]`` for puts.
    """
    f, k = np.asarray(forward, dtype=float), np.asarray(strike, dtype=float)
    d1, d2 = d1_d2(f, k, time, vol)
    call = f * ndtr(d1) - k * ndtr(d2)
    put = k * ndtr(-d2) - f * ndtr(-d1)
    return np.asarray(discount, dtype=float) * np.where(np.asarray(is_call, dtype=bool), call, put)


class Greeks(NamedTuple):
    """Per-contract greeks in the vendor's units.

    :param delta: Forward delta (optionally discounted).
    :param gamma: Change in delta per point of the forward.
    :param vega: Change in price per volatility point.
    :param theta: Change in price per calendar day (negative for long options).
    """

    delta: NDArray[np.float64]
    gamma: NDArray[np.float64]
    vega: NDArray[np.float64]
    theta: NDArray[np.float64]


def greeks(forward: ArrayLike, strike: ArrayLike, time: ArrayLike, vol: ArrayLike, is_call: ArrayLike,
           delta_discount: ArrayLike = 1.0) -> Greeks:
    """Black-76 greeks in the vendor's conventions (see the module description).

    :param forward: Forward F.
    :param strike: Strike K.
    :param time: Time to expiry T in years (positive).
    :param vol: Implied volatility σ.
    :param is_call: True for calls, False for puts.
    :param delta_discount: Factor applied to delta: 1 for the current vendor convention, D = exp(−rT)
        for the vendor's deltas before Jun 25, 2018.
    :returns: Delta, gamma, vega (per point) and theta (per calendar day).
    """
    f, t, s = (np.asarray(a, dtype=float) for a in (forward, time, vol))
    d1, _ = d1_d2(f, strike, t, s)
    pdf = _pdf(d1)
    sqrt_t = np.sqrt(t)
    call = np.asarray(is_call, dtype=bool)
    delta = np.where(call, ndtr(d1), ndtr(d1) - 1.0) * np.asarray(delta_discount, dtype=float)
    gamma = pdf / (f * s * sqrt_t)
    vega = f * pdf * sqrt_t * 0.01
    theta = -f * pdf * s / (2.0 * sqrt_t) / DAYS_PER_YEAR
    return Greeks(delta=delta, gamma=gamma, vega=vega, theta=theta)
