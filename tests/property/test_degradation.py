"""Property tests for R1.2 — convex PWL degradation cost.

Contract: docs/specs/R1.2-degradation.md § "Property tests".
Feasibility guaranteed via soc_initial == soc_terminal (idle always feasible);
degradation only adds a non-negative cost, never makes the model infeasible.
"""

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bess.assets.battery import BatterySpec, DegradationSpec
from bess.optimizer.core import solve

EPS = 1e-6


def tau_max_of(spec: BatterySpec, dt: float) -> float:
    e_max = spec.capacity
    e_min = spec.soc_min * spec.capacity
    power = max(
        spec.eta_charge * spec.p_charge_max * dt, spec.p_discharge_max * dt / spec.eta_discharge
    )
    return min(power, e_max - e_min)


def throughput(spec: BatterySpec, p_ch: float, p_dis: float, dt: float) -> float:
    return spec.eta_charge * p_ch * dt + p_dis / spec.eta_discharge * dt


@st.composite
def degradation(draw):
    """A valid convex DegradationSpec: evenly-spaced φ from 0 to 1 (avoids tiny
    breakpoint gaps), with sorted ⇒ non-decreasing slopes ⇒ convex costs."""
    n_seg = draw(st.integers(min_value=1, max_value=4))
    phi = [i / n_seg for i in range(n_seg + 1)]  # 0 .. 1, gap 1/n_seg
    slopes = sorted(
        draw(st.lists(st.floats(min_value=0.0, max_value=10.0), min_size=n_seg, max_size=n_seg))
    )
    g = [0.0]
    for k in range(1, n_seg + 1):
        g.append(g[-1] + slopes[k - 1] * (phi[k] - phi[k - 1]))
    return DegradationSpec(throughput_pu=phi, cost_eur=g)


@st.composite
def problem_deg(draw):
    n = draw(st.integers(min_value=2, max_value=5))
    prices = draw(
        st.lists(
            st.floats(min_value=-50.0, max_value=200.0, allow_nan=False, allow_infinity=False),
            min_size=n,
            max_size=n,
        )
    )
    capacity = draw(st.floats(min_value=0.5, max_value=5.0))
    anchor = draw(st.floats(min_value=0.0, max_value=1.0))  # per-unit; initial == terminal
    spec = BatterySpec(
        capacity=capacity,
        soc_min=0.0,
        p_charge_max=draw(st.floats(min_value=0.5, max_value=5.0)),
        p_discharge_max=draw(st.floats(min_value=0.5, max_value=5.0)),
        eta_charge=draw(st.floats(min_value=0.8, max_value=1.0)),
        eta_discharge=draw(st.floats(min_value=0.8, max_value=1.0)),
        ramp=None,
        soc_initial=anchor,
        soc_terminal=anchor,
        degradation=draw(degradation()),
    )
    dt = draw(st.sampled_from([0.25, 0.5, 1.0]))
    return prices, spec, dt


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(problem_deg())
def test_invariants_with_degradation(case):
    prices, spec, dt = case
    sched = solve(prices, spec, dt=dt)
    n = len(prices)

    e_min = spec.soc_min * spec.capacity
    e_initial = spec.soc_initial * spec.capacity
    e_terminal = spec.soc_terminal * spec.capacity
    t_max = tau_max_of(spec, dt)

    # R1.1 invariants are untouched by degradation.
    for t in range(n):
        assert -EPS <= sched.p_charge[t] <= spec.p_charge_max + EPS
        assert -EPS <= sched.p_discharge[t] <= spec.p_discharge_max + EPS
        assert not (sched.p_charge[t] > EPS and sched.p_discharge[t] > EPS)
        assert e_min - EPS <= sched.soc[t] <= spec.capacity + EPS

    prev = e_initial
    for t in range(n):
        expected = (
            prev
            + spec.eta_charge * sched.p_charge[t] * dt
            - sched.p_discharge[t] / spec.eta_discharge * dt
        )
        assert sched.soc[t] == pytest.approx(expected, abs=EPS)
        prev = sched.soc[t]
    assert sched.soc[-1] == pytest.approx(e_terminal, abs=EPS)
    assert sched.objective >= -EPS

    # Objective consistency: revenue (grid-side, no efficiency) minus the PWL
    # degradation cost evaluated at the storage-side throughput. This also
    # confirms each D_t equals the PWL value at the optimum.
    revenue = sum(prices[t] * dt * (sched.p_discharge[t] - sched.p_charge[t]) for t in range(n))
    deg_cost = sum(
        spec.degradation.cost_at(
            throughput(spec, sched.p_charge[t], sched.p_discharge[t], dt), t_max
        )
        for t in range(n)
    )
    assert sched.objective == pytest.approx(revenue - deg_cost, abs=1e-5)


@settings(max_examples=200, deadline=None)
@given(
    deg=degradation(),
    t_max=st.floats(min_value=0.5, max_value=5.0),
    u1=st.floats(min_value=0.0, max_value=1.0),
    u2=st.floats(min_value=0.0, max_value=1.0),
)
def test_cost_at_monotone_and_convex(deg, t_max, u1, u2):
    x1, x2 = sorted([u1 * t_max, u2 * t_max])
    c1 = deg.cost_at(x1, t_max)
    c2 = deg.cost_at(x2, t_max)
    # Monotone non-decreasing (the gate's monotonicity property).
    assert c1 <= c2 + EPS
    # Convex: midpoint value <= average of endpoint values.
    mid = deg.cost_at((x1 + x2) / 2, t_max)
    assert mid <= (c1 + c2) / 2 + EPS


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(problem_deg())
def test_degradation_never_pays(case):
    prices, spec, dt = case
    obj_with = solve(prices, spec, dt=dt).objective
    obj_without = solve(prices, spec.model_copy(update={"degradation": None}), dt=dt).objective
    # Degradation is a cost, never a subsidy.
    assert obj_with <= obj_without + EPS
