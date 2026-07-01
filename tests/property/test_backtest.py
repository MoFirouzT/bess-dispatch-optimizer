"""Property tests for the walk-forward backtest.

Contract: docs/specs/R1.4a-backtest.md § "Property tests".
Math: docs/formulation.md § "R1.4 — Backtest semantics (derived; no new model)".
"""

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bess.assets.battery import BatterySpec
from bess.backtest.engine import run_backtest

EPS = 1e-6
# Cross-solve revenue comparisons (V_greedy ≤ V_roll ≤ V*) compare *two independent
# MILP solves*, each carrying HiGHS's ~1e-6 optimality noise, so the ordering must be
# checked above that floor. When the two solves reach the same optimum (e.g. a rolling
# policy that happens to match perfect foresight), V_roll can exceed V* by exactly the
# solver tolerance; EPS = 1e-6 sits right on that floor and loses to float rounding
# (`32.025 + 1e-6` rounds below `32.025001`). A real ordering violation is orders of
# magnitude larger, so 1e-4 preserves the property while absorbing solver noise. The
# tighter EPS still governs within-schedule invariants (SoC continuity, power caps).
EPS_ORDER = 1e-4


@st.composite
def backtest_case(draw):
    """A multi-window toy series + spec. Equal-size windows (total = k * w)."""
    w = draw(st.integers(min_value=1, max_value=4))  # periods per window
    k = draw(st.integers(min_value=1, max_value=3))  # number of windows
    prices = draw(
        st.lists(
            st.floats(min_value=-20.0, max_value=200.0, allow_nan=False, allow_infinity=False),
            min_size=k * w,
            max_size=k * w,
        )
    )
    spec = BatterySpec(
        capacity=draw(st.floats(min_value=0.5, max_value=3.0)),
        soc_min=0.0,
        p_charge_max=draw(st.floats(min_value=0.5, max_value=3.0)),
        p_discharge_max=draw(st.floats(min_value=0.5, max_value=3.0)),
        eta_charge=draw(st.floats(min_value=0.8, max_value=1.0)),
        eta_discharge=draw(st.floats(min_value=0.8, max_value=1.0)),
    )
    dt = draw(st.sampled_from([0.25, 0.5, 1.0]))
    return prices, spec, dt, w


def _check_baseline_feasible(result, spec, dt):
    """Every baseline's schedule obeys the R1.1 physics, per its own segmentation
    (ceiling = one global window; rolling/greedy reset to empty each window)."""
    e_min = spec.soc_min * spec.capacity
    sched = result.schedule
    start = 0
    for size in result.window_sizes:
        prev = e_min  # each segment starts empty
        for t in range(start, start + size):
            assert -EPS <= sched.p_charge[t] <= spec.p_charge_max + EPS
            assert -EPS <= sched.p_discharge[t] <= spec.p_discharge_max + EPS
            assert not (sched.p_charge[t] > EPS and sched.p_discharge[t] > EPS)
            assert e_min - EPS <= sched.soc[t] <= spec.capacity + EPS
            expected = (
                prev
                + spec.eta_charge * sched.p_charge[t] * dt
                - sched.p_discharge[t] / spec.eta_discharge * dt
            )
            assert sched.soc[t] == pytest.approx(expected, abs=EPS)
            prev = sched.soc[t]
        assert prev == pytest.approx(e_min, abs=EPS)  # segment ends empty
        start += size


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(backtest_case())
def test_provable_ordering(case):
    """0 <= V_greedy <= V_roll <= V*  (the core gate of this phase)."""
    prices, spec, dt, w = case
    rep = run_backtest(prices, spec, dt=dt, window=w)
    assert rep.greedy.revenue_eur <= rep.rolling.revenue_eur + EPS_ORDER
    assert rep.rolling.revenue_eur <= rep.perfect_foresight.revenue_eur + EPS_ORDER
    # The *optimal* quantities are floored at idle (0); greedy may be negative.
    assert rep.rolling.revenue_eur >= -EPS


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(backtest_case())
def test_all_baselines_feasible(case):
    prices, spec, dt, w = case
    rep = run_backtest(prices, spec, dt=dt, window=w)
    for result in (rep.greedy, rep.rolling, rep.perfect_foresight):
        _check_baseline_feasible(result, spec, dt)


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(backtest_case())
def test_objective_consistency(case):
    """Each baseline's reported revenue == grid-side cash flow recomputed from its
    own schedule (no efficiency term)."""
    prices, spec, dt, w = case
    rep = run_backtest(prices, spec, dt=dt, window=w)
    for result in (rep.greedy, rep.rolling, rep.perfect_foresight):
        sched = result.schedule
        recomputed = sum(
            prices[t] * dt * (sched.p_discharge[t] - sched.p_charge[t]) for t in range(len(prices))
        )
        assert result.revenue_eur == pytest.approx(recomputed, abs=EPS)


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(backtest_case(), st.floats(min_value=-20.0, max_value=200.0))
def test_no_future_leakage(case, perturbation):
    """Rolling decisions for the first window are invariant to prices in later
    windows (gate C): perturb the last window, the first window is unchanged."""
    prices, spec, dt, w = case
    if len(prices) <= w:  # need at least two windows to perturb a later one
        return
    rep = run_backtest(prices, spec, dt=dt, window=w)

    perturbed = list(prices)
    for t in range(len(prices) - w, len(prices)):  # last window only
        perturbed[t] = perturbation
    rep2 = run_backtest(perturbed, spec, dt=dt, window=w)

    s1, s2 = rep.rolling.schedule, rep2.rolling.schedule
    for t in range(w):  # first window unchanged
        assert s1.p_charge[t] == pytest.approx(s2.p_charge[t], abs=EPS)
        assert s1.p_discharge[t] == pytest.approx(s2.p_discharge[t], abs=EPS)
