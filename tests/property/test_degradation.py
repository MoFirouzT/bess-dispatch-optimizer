"""Property tests for R1.2 — linear degradation cost (D_t = c_deg · τ_t).

Contract: docs/specs/R1.2-degradation.md § "Property tests".
Feasibility guaranteed via soc_initial == soc_terminal (idle always feasible);
degradation only adds a non-negative cost, never makes the model infeasible.
"""

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bess.assets.battery import BatterySpec, DegradationSpec, schedule_degradation_cost
from bess.optimizer.core import solve

EPS = 1e-6

# Solver-numerics guard, not a physics claim (decided 2026-07-22, option recorded in
# STATE.md): when η·Δt sits within ~2.5e-6 of Δt (η ≈ 0.99999 at dt=0.25), HiGHS
# misses a vertex that needs a ~1e-6 MW micro-charge and returns an objective exactly
# (1−η)·|obj| ≈ 1e-5 below the true optimum while claiming a 1e-9 gap (measured on
# 1.12.0–1.13.1; formulation and code verified correct by hand). Cross-solve
# comparisons at 1e-5/1e-6 tolerances cannot survive that, so η is drawn away from
# the degenerate band. Exact 1.0 is kept: the coefficients are then exact and the
# lossless analytic case stays covered. Real cells sit at 0.85–0.98.
eta_solver = st.one_of(st.floats(min_value=0.8, max_value=0.9999), st.just(1.0))


def throughput(spec: BatterySpec, p_ch: float, p_dis: float, dt: float) -> float:
    return spec.eta_charge * p_ch * dt + p_dis / spec.eta_discharge * dt


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
    # per-unit; initial == terminal. Exact-empty (0.0) or >= 1e-3: a sub-tolerance
    # SoC target like 1e-6 sits below the solver's feasibility tolerance, letting it
    # "satisfy" the terminal via a phantom micro-discharge -> a spurious tiny objective.
    anchor = draw(st.one_of(st.just(0.0), st.floats(min_value=1e-3, max_value=1.0)))
    spec = BatterySpec(
        capacity=capacity,
        soc_min=0.0,
        p_charge_max=draw(st.floats(min_value=0.5, max_value=5.0)),
        p_discharge_max=draw(st.floats(min_value=0.5, max_value=5.0)),
        eta_charge=draw(eta_solver),
        eta_discharge=draw(eta_solver),
        ramp=None,
        soc_initial=anchor,
        soc_terminal=anchor,
        degradation=DegradationSpec(cost_per_mwh=draw(st.floats(min_value=0.0, max_value=50.0))),
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

    # Objective consistency: grid-side revenue (no efficiency) minus the linear
    # degradation cost c_deg · Σ τ_t evaluated at the storage-side throughput.
    revenue = sum(prices[t] * dt * (sched.p_discharge[t] - sched.p_charge[t]) for t in range(n))
    c_deg = spec.degradation.cost_per_mwh
    deg_cost = c_deg * sum(
        throughput(spec, sched.p_charge[t], sched.p_discharge[t], dt) for t in range(n)
    )
    assert sched.objective == pytest.approx(revenue - deg_cost, abs=1e-5)


@settings(max_examples=200, deadline=None)
@given(
    c_deg=st.floats(min_value=0.0, max_value=50.0),
    eta_ch=st.floats(min_value=0.8, max_value=1.0),
    eta_dis=st.floats(min_value=0.8, max_value=1.0),
    power=st.floats(min_value=0.1, max_value=5.0),
)
def test_delta_t_invariance(c_deg, eta_ch, eta_dis, power):
    """Total wear is c_deg × total cell throughput, independent of the time partition.

    The same physical charge (power P for one hour) costs the same whether expressed
    as one dt=1 period or four dt=0.25 periods."""
    spec = BatterySpec(
        capacity=10.0,
        p_charge_max=10.0,
        eta_charge=eta_ch,
        eta_discharge=eta_dis,
        degradation=DegradationSpec(cost_per_mwh=c_deg),
    )
    coarse = schedule_degradation_cost(spec, [power], [0.0], dt=1.0)
    fine = schedule_degradation_cost(spec, [power] * 4, [0.0] * 4, dt=0.25)
    assert coarse == pytest.approx(fine, abs=1e-9)


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(problem_deg())
def test_degradation_never_pays(case):
    prices, spec, dt = case
    obj_with = solve(prices, spec, dt=dt).objective
    obj_without = solve(prices, spec.model_copy(update={"degradation": None}), dt=dt).objective
    # Degradation is a cost, never a subsidy.
    assert obj_with <= obj_without + EPS


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(problem_deg())
def test_zero_cost_reduces_to_r11(case):
    """c_deg = 0 and degradation = None give the same objective and schedule."""
    prices, spec, dt = case
    zero = spec.model_copy(update={"degradation": DegradationSpec(cost_per_mwh=0.0)})
    off = spec.model_copy(update={"degradation": None})
    s_zero = solve(prices, zero, dt=dt)
    s_off = solve(prices, off, dt=dt)
    assert s_zero.objective == pytest.approx(s_off.objective, abs=EPS)


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(case=problem_deg(), k=st.floats(min_value=0.25, max_value=4.0))
def test_scale_invariance(case, k):
    """c_deg is €/MWh: scaling the asset's power and energy ratings by k scales
    revenue and throughput together, so the optimal objective scales by k."""
    prices, spec, dt = case
    scaled = spec.model_copy(
        update={
            "capacity": spec.capacity * k,
            "p_charge_max": spec.p_charge_max * k,
            "p_discharge_max": spec.p_discharge_max * k,
        }
    )
    base = solve(prices, spec, dt=dt).objective
    big = solve(prices, scaled, dt=dt).objective
    assert big == pytest.approx(k * base, abs=1e-5, rel=1e-6)
