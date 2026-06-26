"""Golden oracles for R1.2 — convex PWL degradation cost (epigraph form).

Contract: docs/specs/R1.2-degradation.md § "Golden oracles".
Math: docs/formulation.md § "R1.2 — Piecewise-linear degradation cost".

All use a 1 MWh / 1 MW battery, dt=1, e0 = e_tgt = 0. Tolerance 1e-6.
"""

import pytest

from bess.assets.battery import BatterySpec, DegradationSpec
from bess.optimizer.core import solve

TOL = 1e-6


def assert_list_close(actual, expected, tol=TOL):
    assert len(actual) == len(expected), f"length {len(actual)} != {len(expected)}"
    for i, (a, e) in enumerate(zip(actual, expected, strict=True)):
        assert a == pytest.approx(e, abs=tol), f"index {i}: {a} != {e}"


def test_oracle_1_degradation_bites():
    """Convex slope (60) > spread (50) past the kink ⇒ cycle stops at q=0.5.
    Both-direction cost 2·g(q); optimum at the kink. Objective 15."""
    deg = DegradationSpec(throughput_pu=[0.0, 0.5, 1.0], cost_eur=[0.0, 5.0, 35.0])
    spec = BatterySpec(eta_charge=1.0, eta_discharge=1.0, degradation=deg)
    s = solve([0.0, 50.0], spec, dt=1.0)

    assert s.objective == pytest.approx(15.0, abs=TOL)
    assert_list_close(s.p_charge, [0.5, 0.0])
    assert_list_close(s.p_discharge, [0.0, 0.5])
    assert_list_close(s.soc, [0.5, 0.0])


def test_oracle_2_cheap_degradation_full_cycle():
    """Slopes 2, 4 ⇒ 2·slope < 50: full cycle still optimal, profit shaved by 2·g(1)=6."""
    deg = DegradationSpec(throughput_pu=[0.0, 0.5, 1.0], cost_eur=[0.0, 1.0, 3.0])
    spec = BatterySpec(eta_charge=1.0, eta_discharge=1.0, degradation=deg)
    s = solve([0.0, 50.0], spec, dt=1.0)

    assert s.objective == pytest.approx(44.0, abs=TOL)
    assert_list_close(s.p_charge, [1.0, 0.0])
    assert_list_close(s.p_discharge, [0.0, 1.0])
    assert_list_close(s.soc, [1.0, 0.0])


def test_oracle_3_storage_side():
    """η_dis=0.8 ⇒ τ_max=min(1.25,1)=1; throughput is cell-side (τ=q each period).
    A grid-side implementation evaluates g at p_dis=0.8q and lands elsewhere. Objective 10."""
    deg = DegradationSpec(throughput_pu=[0.0, 0.5, 1.0], cost_eur=[0.0, 5.0, 20.0])
    spec = BatterySpec(eta_charge=1.0, eta_discharge=0.8, degradation=deg)
    s = solve([0.0, 50.0], spec, dt=1.0)

    assert s.objective == pytest.approx(10.0, abs=TOL)
    assert_list_close(s.p_charge, [0.5, 0.0])
    assert_list_close(s.p_discharge, [0.0, 0.4])
    assert_list_close(s.soc, [0.5, 0.0])


def test_oracle_4_disabled_matches_r11():
    """degradation=None ⇒ exactly R1.1 oracle 1."""
    spec = BatterySpec(eta_charge=1.0, eta_discharge=1.0)  # degradation defaults None
    s = solve([10.0, 50.0, 20.0], spec, dt=1.0)

    assert s.objective == pytest.approx(40.0, abs=TOL)
    assert_list_close(s.p_charge, [1.0, 0.0, 0.0])
    assert_list_close(s.p_discharge, [0.0, 1.0, 0.0])
    assert_list_close(s.soc, [1.0, 0.0, 0.0])


def test_oracle_5_no_phantom_objective_from_sub_tolerance_cost():
    """Regression: a near-zero degradation curve must not yield a phantom positive.

    Hypothesis-found degenerate case (test_degradation_never_pays): flat prices, a
    cost curve whose only non-zero increment is ~1e-7. The optimum is idle ⇒ exactly
    0. HiGHS presolve used to return D_t = -6.67e-7 (the top segment's line at τ=0),
    inflating the objective to +1.33e-6 > the no-degradation value. solve() now clamps
    that sub-tolerance D_t < 0 (convex PWL is non-negative through the origin), so the
    objective is 0 and never exceeds the degradation-disabled solve."""
    deg = DegradationSpec(
        throughput_pu=[0.0, 1 / 3, 2 / 3, 1.0], cost_eur=[0.0, 0.0, 0.0, 1e-6 / 3]
    )
    spec = BatterySpec(
        eta_charge=1.0, eta_discharge=1.0, soc_initial=0.0, soc_terminal=0.0, degradation=deg
    )
    s = solve([0.0, 0.0], spec, dt=0.25)
    s_off = solve([0.0, 0.0], spec.model_copy(update={"degradation": None}), dt=0.25)

    assert s.objective == pytest.approx(0.0, abs=TOL)
    assert s.objective <= s_off.objective + TOL  # degradation never pays
