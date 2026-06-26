#!/usr/bin/env python3
"""Scaling benchmark — end-to-end solve time vs horizon length.

Times ``optimizer.core.solve`` (build + HiGHS solve + load) on a single full-horizon
problem as the horizon grows from one day to one month. The MILP is one binary and a
handful of continuous variables per period, so it scales benignly; this prints the
numbers rather than asserting them (timings are machine-dependent). Run:

    uv run python examples/benchmark_scaling.py
"""

from __future__ import annotations

from statistics import median
from time import perf_counter

from bess.assets.battery import BatterySpec
from bess.data.fixtures import synthetic_day_ahead
from bess.optimizer.core import solve

HORIZONS_H = [24, 48, 96, 168, 336, 720]  # 1d, 2d, 4d, 1w, 2w, 1mo
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


if __name__ == "__main__":
    main()
