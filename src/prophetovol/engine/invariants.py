"""The accounting invariants, checked at the end of every run (ENG-33).

* Each portfolio snapshot's market value, cash flow, fees, P&L and dollar greeks equal the sum of
  that step's position snapshots.
* Cumulative P&L equals the sum of period P&L: for the portfolio and for each position.
* The sum of all cash flows plus the final market value equals the final cumulative P&L.

Values are compared to 1e-6 dollars (decision 6). A violation raises :class:`InvariantViolation`
naming the step and the security, and fails the run.
"""

from __future__ import annotations

from collections import defaultdict

from prophetovol.core.errors import ProphetoVolError
from prophetovol.results.recorder import RunRecorder

TOLERANCE = 1e-6
"""Largest difference in dollars treated as equal (decision 6)."""

SUMMED = ("market_value", "cash_flow", "fees", "period_pnl", "dollar_delta", "dollar_gamma_1pct", "dollar_vega",
          "dollar_theta")
"""Portfolio fields that are sums of the step's position snapshots."""


class InvariantViolation(ProphetoVolError):
    """An accounting invariant does not hold; the run fails with this diagnostic (ENG-33)."""


def check_invariants(recorder: RunRecorder, tolerance: float = TOLERANCE) -> None:
    """Check ENG-33's invariants on a run's recorded snapshots.

    :param recorder: The run's output.
    :param tolerance: Largest difference treated as equal, in dollars.
    :raises InvariantViolation: At the first violation, naming the step and the security.
    """
    positions = recorder.rows("position_snapshots")
    portfolio = recorder.rows("portfolio_snapshots")

    sums: dict[int, dict[str, float]] = defaultdict(lambda: dict.fromkeys(SUMMED, 0.0))
    for row in positions:
        for k in SUMMED:
            sums[row["step"]][k] += row[k] or 0.0
    for snap in portfolio:
        for k in SUMMED:
            expected = sums[snap["step"]][k]
            if abs(snap[k] - expected) > tolerance:
                raise InvariantViolation(f"step {snap['step']}: portfolio {k} {snap[k]:.6f} differs from the sum of its "
                                         f"position snapshots {expected:.6f}")

    running = 0.0
    for snap in portfolio:
        running += snap["period_pnl"]
        if abs(snap["cumulative_pnl"] - running) > tolerance:
            raise InvariantViolation(f"step {snap['step']}: portfolio cumulative P&L {snap['cumulative_pnl']:.6f} differs "
                                     f"from the sum of period P&L {running:.6f}")
    by_position: dict[str, float] = defaultdict(float)
    for row in positions:
        by_position[row["position_key"]] += row["period_pnl"]
        if abs(row["cumulative_pnl"] - by_position[row["position_key"]]) > tolerance:
            raise InvariantViolation(f"step {row['step']}, {row['position_key']}: cumulative P&L "
                                     f"{row['cumulative_pnl']:.6f} differs from the sum of its period P&L "
                                     f"{by_position[row['position_key']]:.6f}")

    if portfolio:
        cash = sum(snap["cash_flow"] for snap in portfolio)
        final = portfolio[-1]
        if abs(cash + final["market_value"] - final["cumulative_pnl"]) > tolerance:
            raise InvariantViolation(f"step {final['step']}: cash flows {cash:.6f} plus final market value "
                                     f"{final['market_value']:.6f} differ from the final cumulative P&L "
                                     f"{final['cumulative_pnl']:.6f}")
