#!/usr/bin/env python3
"""Extreme-value scenario-tail demo (R2.2b) — empirical body + GPD tail.

Fits a peaks-over-threshold GPD to synthetic forecast residuals, overlays it on the
residual histogram, and shows the un-capping: the plain residual-path bootstrap can
never price a spike above the historical-maximum residual, while the GPD-tail
generator can. Synthetic data only (the no-committed-data rule); numbers are
illustrative, not a gate. Run:

    uv run python examples/spike_tail_demo.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from bess.data.fixtures import synthetic_day_ahead
from bess.scenarios import generate_scenarios
from bess.scenarios.tail import TailModel

FIG = Path(__file__).resolve().parent.parent / "docs" / "figures" / "example-spike-tail.svg"
N_DAYS = 365
N_SCENARIOS = 5000


@dataclass
class _Forecast:
    point: pd.Series


def _gpd_density(x: np.ndarray, *, xi: float, beta: float) -> np.ndarray:
    """GPD pdf of the excess, ``h(y) = (1/β)(1 + ξ y/β)^(−1/ξ − 1)`` (ξ ≠ 0)."""
    if abs(xi) < 1e-12:
        return np.exp(-x / beta) / beta
    return (1.0 / beta) * (1.0 + xi * x / beta) ** (-1.0 / xi - 1.0)


def main() -> None:
    days = N_DAYS
    series = synthetic_day_ahead(days=days).to_numpy().reshape(days, 24).copy()
    # Inject occasional evening scarcity spikes so the residuals are genuinely
    # heavy-tailed (ξ > 0) — the spiky-market regime R2.2b exists for. Synthetic and
    # deliberate: a mechanism demo, not a market result.
    rng = np.random.default_rng(7)
    for d in range(days):
        if rng.random() < 0.05:  # ~5% of days see a scarcity spike at the evening peak
            series[d, 18:21] += rng.exponential(35.0)  # heavy-ish, ξ ≈ 0.2–0.3
    point = series.mean(axis=0)
    residuals = series - point
    index = pd.date_range("2026-01-01", periods=24, freq="h", tz="UTC")
    forecast = _Forecast(point=pd.Series(point, index=index, name="point"))

    tail = TailModel.fit(residuals, threshold_quantile=0.95, side="upper")
    hist_max_resid = float(residuals.max())

    # Plain vs tail-augmented scenario sets; report the support ceiling (max price).
    plain = generate_scenarios(forecast, residuals, n=N_SCENARIOS, seed=0)
    spliced = generate_scenarios(forecast, residuals, n=N_SCENARIOS, seed=0, tail=tail)
    hist_max_price = float(plain.paths.max())
    tail_max_price = float(spliced.paths.max())

    # GPD tail curve over the exceedance region (density, positioned above u).
    y = np.linspace(0.0, hist_max_resid * 1.2, 200)
    exceedance_rate = float(np.mean(residuals > tail.threshold))
    gpd_x = (tail.threshold + y).tolist()
    gpd_density = (exceedance_rate * _gpd_density(y, xi=tail.xi, beta=tail.beta)).tolist()

    print("R2.2b spike-tail demo (synthetic)\n")
    print(f"  threshold u        : {tail.threshold:.1f} €/MWh (95th pct residual)")
    print(f"  GPD fit            : xi={tail.xi:.3f}, beta={tail.beta:.2f}")
    print(f"  historical max resid: {hist_max_resid:.1f} €/MWh")
    print(f"  plain support ceiling: {hist_max_price:.1f} €/MWh (capped)")
    print(f"  + GPD tail ceiling   : {tail_max_price:.1f} €/MWh (un-capped)")

    from bess.viz.backtest_plots import plot_spike_tail

    fig = plot_spike_tail(
        residuals.ravel().tolist(),
        tail.threshold,
        gpd_x,
        gpd_density,
        hist_max_price=hist_max_price,
        tail_max_price=tail_max_price,
    )
    FIG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG, format="svg", bbox_inches="tight")
    print(f"\nwrote {FIG.relative_to(FIG.parent.parent.parent)}")


if __name__ == "__main__":
    main()
