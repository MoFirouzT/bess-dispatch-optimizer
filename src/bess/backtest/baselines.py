"""The three backtest baselines, each over a single window.

Math: ``docs/formulation.md`` § "R1.4 — Backtest semantics". Spec:
``docs/specs/R1.4a-backtest.md``. ``perfect_foresight`` (full horizon) and
``rolling`` (per window) are solves of the existing R1.1/R1.2 optimizer with
**empty** SoC endpoints; ``greedy`` is the feasibility-preserving percentile rule,
which now lives in ``bess.optimizer.heuristics`` (ADR-0010) and is re-exported here
for the engine and the existing backtest callers.

``backtest`` imports ``optimizer``/``assets`` but not the serving chain
(import-linter).
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from bess.assets.battery import BatterySpec
from bess.optimizer.core import Schedule, solve
from bess.optimizer.heuristics import greedy_window

__all__ = ["greedy_window", "solve_window"]


def _empty(spec: BatterySpec) -> BatterySpec:
    """Same asset, forced to start and end **empty** (at ``soc_min``)."""
    return spec.model_copy(update={"soc_initial": spec.soc_min, "soc_terminal": spec.soc_min})


def solve_window(prices: Sequence[float], spec: BatterySpec, dt: float) -> tuple[Schedule, float]:
    """Optimal dispatch over one price block, empty→empty. Returns (schedule, seconds)."""
    t0 = time.perf_counter()
    sched = solve(prices, _empty(spec), dt=dt)
    return sched, time.perf_counter() - t0
