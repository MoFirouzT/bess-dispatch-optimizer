#!/usr/bin/env python3
"""Scaling benchmark — end-to-end solve time vs horizon and scenario count.

Times ``optimizer.core.solve`` (build + HiGHS solve + load) on a single full-horizon
problem as the horizon grows from one day to one month, then the R2.3 two-stage
program (``stochastic.solve_stochastic``, risk-neutral) as the scenario count grows
at a fixed 24 h horizon — the axis where the stochastic layer's cost actually lives
(S + 1 coupled copies of the physics, S·24 + 24 binaries). Prints the numbers rather
than asserting them (timings are machine-dependent). Run:

    uv run python examples/benchmark_scaling.py
"""

from __future__ import annotations

from statistics import median
from time import perf_counter

import numpy as np
import pandas as pd

from bess.assets.battery import BatterySpec
from bess.data.fixtures import synthetic_day_ahead
from bess.optimizer.core import solve
from bess.scenarios import ScenarioSet
from bess.stochastic import solve_stochastic

HORIZONS_H = [24, 48, 96, 168, 336, 720]  # 1d, 2d, 4d, 1w, 2w, 1mo
STOCH_SCENARIOS = [10, 30, 50]  # two-stage program at a fixed 24 h horizon
REPEATS = 3


def main() -> None:
    spec = BatterySpec()  # 1 MWh / 1 MW, η = 0.95
    dt = 1.0
    # One long synthetic series; each horizon takes a prefix of it.
    series = synthetic_day_ahead(days=(max(HORIZONS_H) // 24) + 1).tolist()

    print(f"Scaling benchmark — median of {REPEATS} runs, 1 MWh / 1 MW asset, hourly\n")
    print(f"{'horizon':>10} {'periods':>8} {'median solve (s)':>18}")
    print("-" * 38)
    for h in HORIZONS_H:
        prices = series[:h]
        times = []
        for _ in range(REPEATS):
            t0 = perf_counter()
            solve(prices, spec, dt=dt)
            times.append(perf_counter() - t0)
        label = f"{h}h" if h < 24 * 7 else f"{h // 24}d"
        print(f"{label:>10} {h:>8} {median(times):>18.4f}")

    # Two-stage stochastic program (R2.3): scenario count is the scaling axis.
    days = max(STOCH_SCENARIOS)
    paths = synthetic_day_ahead(days=days + 1).to_numpy(dtype=float)[: days * 24].reshape(-1, 24)
    index = pd.date_range("2026-01-01", periods=24, freq="h", tz="UTC")
    print(f"\nTwo-stage (risk-neutral, rho=0.5, 24 h) — median of {REPEATS} runs\n")
    print(f"{'scenarios':>10} {'binaries':>9} {'median solve (s)':>18}")
    print("-" * 39)
    for s in STOCH_SCENARIOS:
        scen = ScenarioSet(paths=paths[:s], probs=np.full(s, 1.0 / s), index=index)
        times = []
        for _ in range(REPEATS):
            t0 = perf_counter()
            solve_stochastic(scen, spec, rho=0.5)
            times.append(perf_counter() - t0)
        print(f"{s:>10} {(s + 1) * 24:>9} {median(times):>18.4f}")


if __name__ == "__main__":
    main()
