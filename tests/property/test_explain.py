"""Property tests for R2.4 — shadow-price explainability.

Contract: docs/specs/R2.4-explainability.md § "Property tests".
Math: docs/formulation.md § "R2.4. Shadow-price explainability".

Feasibility is guaranteed via soc_initial == soc_terminal (idle is always feasible),
matching tests/property/test_degradation.py. The invariants bind the reported duals
to the dispatch they claim to explain.

Failing until `bess.explain.duals` is implemented (test-first, R2.4 build task).
"""

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bess.assets.battery import BatterySpec, DegradationSpec
from bess.explain.duals import explain_schedule
from bess.optimizer.core import solve

EPS = 1e-6


@st.composite
def problem(draw):
    n = draw(st.integers(min_value=2, max_value=6))
    prices = draw(
        st.lists(
            st.floats(min_value=-60.0, max_value=200.0, allow_nan=False, allow_infinity=False),
            min_size=n,
            max_size=n,
        )
    )
    anchor = draw(st.one_of(st.just(0.0), st.floats(min_value=1e-3, max_value=0.9)))
    deg = draw(st.one_of(st.none(), st.floats(min_value=0.0, max_value=25.0)))
    spec = BatterySpec(
        capacity=draw(st.floats(min_value=0.5, max_value=4.0)),
        soc_min=0.0,
        p_charge_max=draw(st.floats(min_value=0.5, max_value=2.0)),
        p_discharge_max=draw(st.floats(min_value=0.5, max_value=2.0)),
        eta_charge=draw(st.floats(min_value=0.8, max_value=1.0)),
        eta_discharge=draw(st.floats(min_value=0.8, max_value=1.0)),
        ramp=None,
        soc_initial=anchor,
        soc_terminal=anchor,
        degradation=None if deg is None else DegradationSpec(cost_per_mwh=deg),
    )
    dt = draw(st.sampled_from([0.25, 0.5, 1.0]))
    return prices, spec, dt


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(problem())
def test_soundness_resolved_objective_equals_milp(case):
    """The re-solved LP objective equals the MILP's; the guard on the relaxation.

    This is the property that would have caught the negative-price dump, and the
    reason the idle relaxation is restricted to pi >= 0.
    """
    prices, spec, dt = case
    milp = solve(prices, spec, dt=dt)
    exp = explain_schedule(prices, spec, dt=dt)
    assert exp.schedule.objective == pytest.approx(milp.objective, abs=1e-5)


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(problem())
def test_flat_water_value_on_interior_soc(case):
    """mu_t = mu_{t+1} wherever e_min < e_t < e_max (the water value steps only at a
    bound). This is what lets one number explain a whole run."""
    prices, spec, dt = case
    exp = explain_schedule(prices, spec, dt=dt)
    e_min, e_max = spec.soc_min * spec.capacity, spec.capacity
    mu = [p.water_value_eur_mwh for p in exp.periods]
    soc = exp.schedule.soc
    for t in range(len(prices) - 1):
        if e_min + 1e-6 < soc[t] < e_max - 1e-6:
            assert mu[t] == pytest.approx(mu[t + 1], abs=1e-4)


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(problem())
def test_band_consistency_where_reported(case):
    """Wherever a band is reported, the period's action agrees with it: charge below
    the low edge, discharge above the high edge, idle inside. Bind the dual to the
    dispatch. Not asserted where no band is reported (unpinned fallback runs)."""
    prices, spec, dt = case
    exp = explain_schedule(prices, spec, dt=dt)
    slack = 1e-4
    for p in exp.periods:
        if p.band_low_eur_mwh is None:
            continue
        lo, hi = p.band_low_eur_mwh, p.band_high_eur_mwh
        tol = slack * max(1.0, abs(lo), abs(hi))
        if p.action == "charge":
            assert p.price_eur_mwh <= lo + tol
        elif p.action == "discharge":
            assert p.price_eur_mwh >= hi - tol
        else:
            assert lo - tol <= p.price_eur_mwh <= hi + tol


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(problem())
def test_band_reported_iff_run_pinned(case):
    """A period carries band edges iff its run is pinned. Guards the OQ2 decision
    against being widened to unpinned runs (where the band fails most of the time)."""
    prices, spec, dt = case
    exp = explain_schedule(prices, spec, dt=dt)
    for p in exp.periods:
        pinned = exp.runs[p.run].pinned
        has_band = p.band_low_eur_mwh is not None
        assert has_band == pinned


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(problem())
def test_pinnedness_is_a_run_property(case):
    """Every period's `run` index points to a run that lists it, and a run's pinned
    flag is shared by all its periods (pinnedness is constant within a flat run)."""
    prices, spec, dt = case
    exp = explain_schedule(prices, spec, dt=dt)
    covered = sorted(t for r in exp.runs for t in r.periods)
    assert covered == list(range(len(prices)))  # runs partition the horizon
    for i, r in enumerate(exp.runs):
        for t in r.periods:
            assert exp.periods[t].run == i


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(problem())
def test_breakeven_slippage_non_negative_at_trades(case):
    """An executed trade clears its zero-slippage threshold, so it can absorb >= 0
    transaction cost. A negative value would be an optimality violation."""
    prices, spec, dt = case
    exp = explain_schedule(prices, spec, dt=dt)
    for p in exp.periods:
        if p.action == "idle":
            assert p.breakeven_slippage_eur_mwh is None
        else:
            assert p.breakeven_slippage_eur_mwh is not None
            assert p.breakeven_slippage_eur_mwh >= -1e-5


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(problem())
def test_marginal_value_matches_finite_difference(case):
    """Where the MILP value has no kink in e_0 (the two one-sided differences agree),
    mu_1 equals dV/de_0. Necessary, not sufficient: all three candidate idle rules
    pass this, which is why golden oracle 1 exists to separate them."""
    prices, spec, dt = case
    eps = 1e-4
    d = eps / spec.capacity
    if not (spec.soc_min + d <= spec.soc_initial <= 1.0 - d):
        return  # keep the perturbation inside the SoC box
    base = solve(prices, spec, dt=dt).objective
    up = solve(
        prices, spec.model_copy(update={"soc_initial": spec.soc_initial + d}), dt=dt
    ).objective
    dn = solve(
        prices, spec.model_copy(update={"soc_initial": spec.soc_initial - d}), dt=dt
    ).objective
    right, left = (up - base) / eps, (base - dn) / eps
    if abs(right - left) > 1e-3:
        return  # a kink: no single dual is "the" answer
    mu1 = explain_schedule(prices, spec, dt=dt).periods[0].water_value_eur_mwh
    assert mu1 == pytest.approx(0.5 * (right + left), abs=1e-3)


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(case=problem(), k=st.floats(min_value=0.25, max_value=4.0))
def test_scale_invariance_of_water_value(case, k):
    """The water value is a per-MWh rate: scaling capacity, both power caps, and the
    SoC endpoints by k > 0 leaves every mu_t unchanged. Mirrors the R1.2 property."""
    prices, spec, dt = case
    scaled = spec.model_copy(
        update={
            "capacity": spec.capacity * k,
            "p_charge_max": spec.p_charge_max * k,
            "p_discharge_max": spec.p_discharge_max * k,
        }
    )
    base = [p.water_value_eur_mwh for p in explain_schedule(prices, spec, dt=dt).periods]
    big = [p.water_value_eur_mwh for p in explain_schedule(prices, scaled, dt=dt).periods]
    for a, b in zip(base, big, strict=True):
        assert a == pytest.approx(b, abs=1e-4, rel=1e-5)


@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(problem())
def test_determinism(case):
    """Fixed inputs give bit-stable water values."""
    prices, spec, dt = case
    a = [p.water_value_eur_mwh for p in explain_schedule(prices, spec, dt=dt).periods]
    b = [p.water_value_eur_mwh for p in explain_schedule(prices, spec, dt=dt).periods]
    assert a == b
