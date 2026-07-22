"""Property tests for the R1.5 dispatch circuit breaker.

Contract: docs/specs/R1.5-serving.md § "Property tests" + § "Acceptance gate".
For any pre-flight-valid request the breaker returns a *feasible* schedule in both
modes, never raises on solver failure, and the greedy fallback never beats the
optimum (V_greedy ≤ V*, formulation §R1.4).
"""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bess.api.service import dispatch
from bess.assets.battery import BatterySpec
from bess.optimizer.core import Schedule

EPS = 1e-6


def _feasible(sched: Schedule, spec: BatterySpec, dt: float) -> bool:
    e_min = spec.soc_min * spec.capacity
    prev = e_min
    for t in range(len(sched.p_charge)):
        if not (-EPS <= sched.p_charge[t] <= spec.p_charge_max + EPS):
            return False
        if not (-EPS <= sched.p_discharge[t] <= spec.p_discharge_max + EPS):
            return False
        if sched.p_charge[t] > EPS and sched.p_discharge[t] > EPS:
            return False
        if not (e_min - EPS <= sched.soc[t] <= spec.capacity + EPS):
            return False
        expected = (
            prev
            + spec.eta_charge * sched.p_charge[t] * dt
            - sched.p_discharge[t] / spec.eta_discharge * dt
        )
        if abs(sched.soc[t] - expected) > EPS:
            return False
        prev = sched.soc[t]
    return abs(prev - e_min) <= EPS


_eta_solver = st.one_of(st.floats(min_value=0.8, max_value=0.9999), st.just(1.0))


@st.composite
def valid_request(draw):
    n = draw(st.integers(min_value=1, max_value=6))
    prices = draw(
        st.lists(
            st.floats(min_value=-50.0, max_value=200.0, allow_nan=False, allow_infinity=False),
            min_size=n,
            max_size=n,
        )
    )
    spec = BatterySpec(
        capacity=draw(st.floats(min_value=0.5, max_value=5.0)),
        soc_min=0.0,
        p_charge_max=draw(st.floats(min_value=0.5, max_value=5.0)),
        p_discharge_max=draw(st.floats(min_value=0.5, max_value=5.0)),
        # η clear of the ~0.99999 solver band; see the note on eta_solver in test_degradation.py
        eta_charge=draw(_eta_solver),
        eta_discharge=draw(_eta_solver),
        soc_initial=0.0,  # empty -> empty: always pre-flight feasible
        soc_terminal=0.0,
    )
    dt = draw(st.sampled_from([0.25, 0.5, 1.0]))
    return prices, spec, dt


def _boom(*a, **k):
    raise RuntimeError("forced solver failure")


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(valid_request())
def test_breaker_feasible_in_both_modes_and_floor_holds(case):
    prices, spec, dt = case

    opt = dispatch(prices, spec, dt, budget=5.0)
    assert opt.mode == "optimal"
    assert _feasible(opt.schedule, spec, dt)

    fb = dispatch(prices, spec, dt, budget=5.0, solve_fn=_boom)
    assert fb.mode == "fallback_greedy"
    assert _feasible(fb.schedule, spec, dt)

    # The greedy fallback is a floor: it never beats the optimum.
    assert fb.objective <= opt.objective + EPS
