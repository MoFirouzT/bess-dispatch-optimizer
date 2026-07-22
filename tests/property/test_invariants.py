"""Property tests — invariants that hold for ANY valid input, checked against
inputs the implementation did not choose.

Contract: docs/specs/R1.1-deterministic-core.md § "Property tests".
Math: docs/formulation.md § "R1.1 — Deterministic core".

Feasibility: every generated instance uses soc_initial == soc_terminal, so the
all-idle schedule (SoC held constant, net power 0) is always feasible — the
solver therefore always returns an optimal schedule, never Infeasible.
"""

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bess.assets.battery import BatterySpec
from bess.optimizer.core import solve

EPS = 1e-6

_prices = st.floats(min_value=-50.0, max_value=200.0, allow_nan=False, allow_infinity=False)
# η clear of the ~0.99999 solver band; see the note on eta_solver in test_degradation.py
_eta = st.one_of(st.floats(min_value=0.8, max_value=0.9999), st.just(1.0))
_power = st.floats(min_value=0.5, max_value=5.0)


@st.composite
def problem(draw, ramp_enabled=False):
    """A feasible (prices, BatterySpec, dt). soc_initial == soc_terminal."""
    n = draw(st.integers(min_value=2, max_value=6))
    prices = draw(st.lists(_prices, min_size=n, max_size=n))
    capacity = draw(st.floats(min_value=0.5, max_value=5.0))
    soc_anchor = draw(st.floats(min_value=0.0, max_value=1.0))  # per-unit (fraction of capacity)
    ramp = draw(st.floats(min_value=0.5, max_value=10.0)) if ramp_enabled else None
    spec = BatterySpec(
        capacity=capacity,
        soc_min=0.0,
        p_charge_max=draw(_power),
        p_discharge_max=draw(_power),
        eta_charge=draw(_eta),
        eta_discharge=draw(_eta),
        ramp=ramp,
        soc_initial=soc_anchor,
        soc_terminal=soc_anchor,
    )
    dt = draw(st.sampled_from([0.25, 0.5, 1.0]))
    return prices, spec, dt


def assert_core_invariants(sched, prices, spec, dt):
    """The R1.1 invariant block, shared by the Hypothesis sweep and the weekly-scale pin."""
    n = len(prices)

    # Per-unit config -> absolute MWh (the schedule's soc is in MWh).
    e_min = spec.soc_min * spec.capacity
    e_initial = spec.soc_initial * spec.capacity
    e_terminal = spec.soc_terminal * spec.capacity

    for t in range(n):
        # Power caps (non-negative, within inverter limits).
        assert -EPS <= sched.p_charge[t] <= spec.p_charge_max + EPS
        assert -EPS <= sched.p_discharge[t] <= spec.p_discharge_max + EPS
        # Mutual exclusion: never charge and discharge in the same period.
        assert not (sched.p_charge[t] > EPS and sched.p_discharge[t] > EPS)
        # SoC bounds.
        assert e_min - EPS <= sched.soc[t] <= spec.capacity + EPS

    # SoC continuity (exact): efficiency lives here, grid-side.
    prev = e_initial
    for t in range(n):
        expected = (
            prev
            + spec.eta_charge * sched.p_charge[t] * dt
            - sched.p_discharge[t] / spec.eta_discharge * dt
        )
        assert sched.soc[t] == pytest.approx(expected, abs=EPS)
        prev = sched.soc[t]

    # Terminal SoC.
    assert sched.soc[-1] == pytest.approx(e_terminal, abs=EPS)

    # Objective consistency: grid-side cash flow, NO efficiency term.
    recomputed = sum(prices[t] * dt * (sched.p_discharge[t] - sched.p_charge[t]) for t in range(n))
    assert sched.objective == pytest.approx(recomputed, abs=EPS)

    # Objective floor: idle is always feasible, so the optimum is never negative.
    assert sched.objective >= -EPS


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(problem())
def test_core_invariants(case):
    prices, spec, dt = case
    assert_core_invariants(solve(prices, spec, dt=dt), prices, spec, dt)


def test_core_invariants_weekly_scale():
    """The same invariants once at a realistic weekly horizon (T = 168).

    The Hypothesis sweep stays at T ≤ 6 so 200 examples run fast; this pins the
    invariant block at production scale on a seeded random curve, so a pathology
    that only appears on long horizons (accumulating SoC drift, a binary pattern
    the small instances never reach) cannot hide behind the toy sizes."""
    rng = np.random.default_rng(42)
    prices = rng.uniform(-50.0, 200.0, size=168).tolist()
    spec = BatterySpec(
        capacity=2.0,
        p_charge_max=1.0,
        p_discharge_max=1.0,
        eta_charge=0.95,
        eta_discharge=0.95,
        soc_initial=0.5,
        soc_terminal=0.5,
    )
    assert_core_invariants(solve(prices, spec, dt=1.0), prices, spec, dt=1.0)


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    price=st.floats(min_value=0.0, max_value=200.0, allow_nan=False, allow_infinity=False),
    n=st.integers(min_value=2, max_value=6),
)
def test_no_phantom_profit_when_prices_equal_and_nonnegative(price, n):
    """Flat, non-negative price => no arbitrage => idle is optimal => objective ~ 0.

    Restricted to price >= 0: under uniformly negative prices the battery
    legitimately profits as a paid load (see golden oracle 4), so the bound
    does not hold there.
    """
    spec = BatterySpec()  # defaults; soc_initial == soc_terminal == 0
    sched = solve([price] * n, spec, dt=1.0)
    assert sched.objective <= EPS


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(problem(ramp_enabled=True))
def test_ramp_respected_when_enabled(case):
    """|p_net[t] - p_net[t-1]| <= R for t >= 2, with p_net = p_dis - p_ch."""
    prices, spec, dt = case
    sched = solve(prices, spec, dt=dt)
    net = [sched.p_discharge[t] - sched.p_charge[t] for t in range(len(prices))]
    for t in range(1, len(net)):
        assert abs(net[t] - net[t - 1]) <= spec.ramp + EPS
