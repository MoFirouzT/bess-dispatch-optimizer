#!/usr/bin/env python3
"""Scenario reduction demo (R2.2) — the count-vs-distance / count-vs-time trade-off.

Builds a scenario set by residual-path bootstrap off a synthetic day-ahead shape,
reduces it to a sweep of kept counts with fast forward selection (and the k-means
baseline), and writes the trade-off figure to ``docs/figures/``. Synthetic data
only (the no-committed-data rule); numbers are illustrative, not a gate. Run:

    uv run python examples/scenario_reduction_demo.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from bess.data.fixtures import synthetic_day_ahead
from bess.scenarios import generate_scenarios, reduce_scenarios

N_GENERATE = 300
KEPT_COUNTS = [5, 10, 20, 30, 50, 75, 100, 150]
FIG = Path(__file__).resolve().parent.parent / "docs" / "figures" / "example-scenario-reduction.svg"


@dataclass
class _Forecast:
    """Stand-in exposing the ``point`` series the generator reads."""

    point: pd.Series


def _build_scenarios() -> tuple[object, np.ndarray]:
    # A year of synthetic days -> a mean daily shape (the "point forecast") plus that
    # many whole-day residual vectors (each day minus the mean), so the bootstrap draws
    # from realistic, temporally-correlated error paths (a bank larger than the kept
    # counts, so distance falls smoothly rather than collapsing to a few distinct atoms).
    days = 365
    series = synthetic_day_ahead(days=days).to_numpy().reshape(days, 24)
    point = series.mean(axis=0)
    residuals = series - point
    index = pd.date_range("2026-01-01", periods=24, freq="h", tz="UTC")
    forecast = _Forecast(point=pd.Series(point, index=index, name="point"))
    return forecast, residuals


def main() -> None:
    forecast, residuals = _build_scenarios()
    scenarios = generate_scenarios(forecast, residuals, n=N_GENERATE, seed=0)

    dist_forward, dist_kmeans, times_ms = [], [], []
    for k in KEPT_COUNTS:
        t0 = perf_counter()
        _, d_fwd = reduce_scenarios(scenarios, n_reduced=k, method="forward", p=2)
        times_ms.append((perf_counter() - t0) * 1e3)
        _, d_km = reduce_scenarios(scenarios, n_reduced=k, method="kmeans", p=2, seed=0)
        dist_forward.append(d_fwd)
        dist_kmeans.append(d_km)

    print(f"Scenario reduction — {N_GENERATE} generated, p=2 Kantorovich distance\n")
    print(f"{'kept':>6} {'forward':>12} {'k-means':>12} {'time (ms)':>12}")
    print("-" * 44)
    for k, df, dk, tm in zip(KEPT_COUNTS, dist_forward, dist_kmeans, times_ms, strict=True):
        print(f"{k:>6} {df:>12.3f} {dk:>12.3f} {tm:>12.2f}")

    from bess.viz.backtest_plots import plot_scenario_reduction

    fig = plot_scenario_reduction(
        KEPT_COUNTS, dist_forward, times_ms, dist_kmeans=dist_kmeans, n_generate=N_GENERATE
    )
    FIG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG, format="svg", bbox_inches="tight")
    print(f"\nwrote {FIG.relative_to(FIG.parent.parent.parent)}")


if __name__ == "__main__":
    main()
