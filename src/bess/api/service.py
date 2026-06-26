"""Dispatch circuit breaker — the serving-side decision logic (ADR-0011).

Pure function over ``(prices, spec, dt)`` with injectable ``solve_fn``/``greedy_fn``
so each branch is testable without HTTP or real solver stress. Two failure classes,
two outcomes:

- **invalid input** (pre-flight ``PreflightError``) propagates: the request is wrong
  and no schedule can repair it (the app maps it to HTTP 422);
- **valid input, no optimum in budget** (solver over ``time_limit``, non-optimal, or
  raising; or the wall-clock overshoots the budget) degrades to the **greedy**
  schedule and is logged.

``api`` may import ``optimizer``/``validation``/``assets`` (import-linter layers).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from time import perf_counter

from bess.assets.battery import BatterySpec
from bess.optimizer.core import Schedule, solve
from bess.optimizer.heuristics import greedy_window
from bess.validation.preflight import check

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DispatchResult:
    """Outcome of one dispatch decision. ``mode`` is ``"optimal"`` or ``"fallback_greedy"``."""

    mode: str
    schedule: Schedule
    objective: float
    solve_seconds: float
    solver_termination: str


def dispatch(
    prices: Sequence[float],
    spec: BatterySpec,
    dt: float,
    *,
    budget: float,
    charge_pct: float = 20.0,
    discharge_pct: float = 80.0,
    solve_fn: Callable[..., Schedule] = solve,
    greedy_fn: Callable[..., Schedule] = greedy_window,
) -> DispatchResult:
    """Return the optimal dispatch, or the greedy fallback if the solver misses budget.

    Raises ``PreflightError`` for invalid / provably-infeasible input (the breaker
    refuses to mask bad input behind a fallback). For any pre-flight-valid input this
    always returns a feasible schedule, never raising on solver failure.
    """
    # Invalid input is surfaced, never served as greedy: validate up front, outside
    # the fallback try/except so a PreflightError cannot be swallowed.
    check(prices, spec, dt)

    t0 = perf_counter()
    try:
        sched = solve_fn(prices, spec, dt, time_limit=budget)
        elapsed = perf_counter() - t0
        if elapsed > budget:
            # The solver returned an optimum but the operation blew the latency SLA
            # (build + solve + load). Degrade to the fast greedy answer.
            raise TimeoutError(f"dispatch exceeded latency budget: {elapsed:.3f}s > {budget:.3f}s")
        return DispatchResult("optimal", sched, sched.objective, elapsed, sched.termination)
    except Exception as exc:
        log.warning("dispatch falling back to greedy schedule: %s", exc)
        g = greedy_fn(prices, spec, dt, charge_pct=charge_pct, discharge_pct=discharge_pct)
        return DispatchResult("fallback_greedy", g, g.objective, perf_counter() - t0, "fallback")
