"""Property tests for the pre-flight validator.

Contract: docs/specs/R1.3-validation.md § "Property tests".
Math: docs/formulation.md § "R1.3 — Pre-flight feasibility (derived; no new model)".

Soundness/completeness are checked against the *raw* solver (bypassing the
auto-check wired into solve()), so the validator's verdict is tested against
ground truth, not against itself.
"""

import math

import pyomo.environ as pyo
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pyomo.opt import TerminationCondition

from bess.assets.battery import BatterySpec
from bess.optimizer.core import build_model, solve
from bess.validation.preflight import IssueCode, PreflightError, validate

EPS = 1e-6

_REACH_CODES = {IssueCode.TERMINAL_UNREACHABLE_CHARGE, IssueCode.TERMINAL_UNREACHABLE_DISCHARGE}


def _raw_termination(prices, spec, dt):
    """Solver verdict on the raw model, bypassing the pre-flight auto-check.

    ``load_solutions=False`` so an infeasible model returns its termination
    condition instead of raising on the (absent) solution load.
    """
    model = build_model(prices, spec, dt)
    results = pyo.SolverFactory("appsi_highs").solve(model, load_solutions=False)
    return results.solver.termination_condition


_eta_solver = st.one_of(st.floats(min_value=0.8, max_value=0.9999), st.just(1.0))


@st.composite
def reachability_case(draw, ramp_enabled=False):
    """A clean (finite, non-empty, dt>0) instance with independent initial/terminal
    SoC, so reachable and unreachable targets both occur. Tight-ish power makes
    unreachable cases common at short horizons."""
    n = draw(st.integers(min_value=1, max_value=4))
    prices = draw(
        st.lists(
            st.floats(min_value=-50.0, max_value=200.0, allow_nan=False, allow_infinity=False),
            min_size=n,
            max_size=n,
        )
    )
    capacity = draw(st.floats(min_value=0.5, max_value=5.0))
    soc_min = draw(st.floats(min_value=0.0, max_value=0.3))
    soc_initial = draw(st.floats(min_value=soc_min, max_value=1.0))
    soc_terminal = draw(st.floats(min_value=soc_min, max_value=1.0))
    ramp = draw(st.floats(min_value=0.3, max_value=10.0)) if ramp_enabled else None
    spec = BatterySpec(
        capacity=capacity,
        soc_min=soc_min,
        p_charge_max=draw(st.floats(min_value=0.3, max_value=1.5)),
        p_discharge_max=draw(st.floats(min_value=0.3, max_value=1.5)),
        # η clear of the ~0.99999 solver band; see the note on eta_solver in test_degradation.py
        eta_charge=draw(_eta_solver),
        eta_discharge=draw(_eta_solver),
        ramp=ramp,
        soc_initial=soc_initial,
        soc_terminal=soc_terminal,
    )
    dt = draw(st.sampled_from([0.25, 0.5, 1.0]))
    return prices, spec, dt


# --- Total / pure -----------------------------------------------------------

_any_dt = st.one_of(
    st.floats(allow_nan=True, allow_infinity=True),
    st.sampled_from([0.0, -1.0, 0.25, 1.0]),
)


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    prices=st.lists(st.floats(allow_nan=True, allow_infinity=True), max_size=8),
    dt=_any_dt,
)
def test_validate_is_total(prices, dt):
    """validate never raises and always returns a list, for arbitrary prices/dt."""
    spec = BatterySpec()  # any valid spec; pre-flight assumes the spec is already valid
    out = validate(prices, spec, dt)
    assert isinstance(out, list)


# --- Soundness: no false positives on reachability (ramp on OR off) ----------


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(reachability_case(ramp_enabled=False))
def test_reachability_sound_no_ramp(case):
    _assert_sound(case)


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(reachability_case(ramp_enabled=True))
def test_reachability_sound_with_ramp(case):
    _assert_sound(case)


def _assert_sound(case):
    prices, spec, dt = case
    issues = validate(prices, spec, dt)
    if any(i.code in _REACH_CODES for i in issues):
        # Necessary condition violated => the raw model is genuinely infeasible.
        assert _raw_termination(prices, spec, dt) != TerminationCondition.optimal


# --- Completeness: ramp-free reachable => solver optimal --------------------


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(reachability_case(ramp_enabled=False))
def test_reachability_complete_no_ramp(case):
    prices, spec, dt = case
    issues = validate(prices, spec, dt)
    if not issues:  # clean AND reachable
        assert _raw_termination(prices, spec, dt) == TerminationCondition.optimal


# --- solve() integration: raises PreflightError iff validate finds issues ----


@st.composite
def maybe_dirty_case(draw):
    """A ramp-free case, sometimes corrupted (empty / NaN price / dt<=0 /
    unreachable endpoints), to exercise both branches of the integration."""
    prices, spec, dt = draw(reachability_case(ramp_enabled=False))
    kind = draw(st.sampled_from(["clean", "empty", "nan_price", "bad_dt"]))
    if kind == "empty":
        prices = []
    elif kind == "nan_price" and prices:
        prices = list(prices)
        prices[draw(st.integers(0, len(prices) - 1))] = math.nan
    elif kind == "bad_dt":
        dt = 0.0
    return prices, spec, dt


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(maybe_dirty_case())
def test_solve_raises_iff_validate_finds_issues(case):
    prices, spec, dt = case
    issues = validate(prices, spec, dt)
    if issues:
        with pytest.raises(PreflightError) as exc:
            solve(prices, spec, dt=dt)
        assert {i.code for i in exc.value.issues} == {i.code for i in issues}
    else:
        sched = solve(prices, spec, dt=dt)  # ramp-free + clean => solvable
        assert len(sched.soc) == len(prices)


# --- No regression: known-good inputs never blocked -------------------------


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    n=st.integers(min_value=2, max_value=6),
    price=st.floats(min_value=-50.0, max_value=200.0, allow_nan=False, allow_infinity=False),
    soc=st.floats(min_value=0.0, max_value=1.0),
    dt=st.sampled_from([0.25, 0.5, 1.0]),
)
def test_clean_equal_endpoints_never_blocked(n, price, soc, dt):
    """soc_initial == soc_terminal (the R1.1/R1.2 strategy shape) is always
    reachable (idle) => validate returns []."""
    spec = BatterySpec(soc_initial=soc, soc_terminal=soc)
    assert validate([price] * n, spec, dt) == []
