"""Unit tests for the dispatch circuit breaker (bess.api.service.dispatch).

Contract: docs/specs/R1.5-serving.md § "Property tests" + ADR-0011. The breaker is
a pure function with injectable solve_fn/greedy_fn, so each branch (optimal,
greedy fallback, invalid input) is forced deterministically without HTTP or real
solver stress.
"""

import pytest

from bess.api.service import DispatchResult, dispatch
from bess.assets.battery import BatterySpec
from bess.optimizer.core import Schedule, solve
from bess.optimizer.heuristics import greedy_window
from bess.validation.preflight import PreflightError

SPEC = BatterySpec(eta_charge=1.0, eta_discharge=1.0)
PRICES = [10.0, 50.0, 20.0]


def _feasible(sched: Schedule, spec: BatterySpec, dt: float, eps: float = 1e-6) -> bool:
    """A single schedule satisfies the physical constraints and ends empty."""
    e_min = spec.soc_min * spec.capacity
    prev = e_min
    for t in range(len(sched.p_charge)):
        if not (-eps <= sched.p_charge[t] <= spec.p_charge_max + eps):
            return False
        if not (-eps <= sched.p_discharge[t] <= spec.p_discharge_max + eps):
            return False
        if sched.p_charge[t] > eps and sched.p_discharge[t] > eps:
            return False
        if not (e_min - eps <= sched.soc[t] <= spec.capacity + eps):
            return False
        expected = (
            prev
            + spec.eta_charge * sched.p_charge[t] * dt
            - sched.p_discharge[t] / spec.eta_discharge * dt
        )
        if abs(sched.soc[t] - expected) > eps:
            return False
        prev = sched.soc[t]
    return abs(prev - e_min) <= eps


def test_optimal_path_matches_solver():
    res = dispatch(PRICES, SPEC, 1.0, budget=2.0)
    assert isinstance(res, DispatchResult)
    assert res.mode == "optimal"
    assert res.solver_termination == "optimal"
    assert res.objective == pytest.approx(solve(PRICES, SPEC, dt=1.0).objective)
    assert _feasible(res.schedule, SPEC, 1.0)


def test_solver_failure_falls_back_to_greedy():
    def boom(*a, **k):
        raise RuntimeError("solver exploded")

    res = dispatch(PRICES, SPEC, 1.0, budget=2.0, solve_fn=boom)
    assert res.mode == "fallback_greedy"
    assert res.solver_termination == "fallback"
    expected = greedy_window(PRICES, SPEC, 1.0, charge_pct=20.0, discharge_pct=80.0)
    assert res.objective == pytest.approx(expected.objective)
    assert res.schedule.p_discharge == pytest.approx(expected.p_discharge)
    assert _feasible(res.schedule, SPEC, 1.0)


def test_wall_clock_overshoot_falls_back():
    # solve_fn returns a valid optimum but reports taking longer than the budget;
    # the wall-clock guard degrades to greedy to honor the latency SLA.
    slow = solve(PRICES, SPEC, dt=1.0)

    def slow_solve(*a, **k):
        import time

        time.sleep(0.05)
        return slow

    res = dispatch(PRICES, SPEC, 1.0, budget=0.001, solve_fn=slow_solve)
    assert res.mode == "fallback_greedy"


def test_invalid_input_raises_preflight_not_fallback():
    # Empty horizon is invalid input; the breaker must surface it, never serve greedy.
    with pytest.raises(PreflightError):
        dispatch([], SPEC, 1.0, budget=2.0)


def test_never_raises_on_valid_input_even_if_solver_dies():
    def boom(*a, **k):
        raise RuntimeError("boom")

    # Any pre-flight-valid request returns a feasible schedule, never an exception.
    res = dispatch(PRICES, SPEC, 1.0, budget=2.0, solve_fn=boom)
    assert _feasible(res.schedule, SPEC, 1.0)


def test_fallback_objective_never_beats_optimum():
    opt = dispatch(PRICES, SPEC, 1.0, budget=2.0).objective

    def boom(*a, **k):
        raise RuntimeError("boom")

    fb = dispatch(PRICES, SPEC, 1.0, budget=2.0, solve_fn=boom).objective
    assert fb <= opt + 1e-6
