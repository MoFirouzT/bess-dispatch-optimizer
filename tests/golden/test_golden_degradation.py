"""Golden oracles for R1.2 — linear degradation cost (D_t = c_deg · τ_t).

Contract: docs/specs/R1.2-degradation.md § "Golden oracles".
Math: docs/formulation.md § "R1.2. Degradation cost".

All use a 1 MWh / 1 MW battery, dt=1, e0 = e_tgt = 0. Tolerance 1e-6.

A linear cost makes the cycle bang-bang: with a constant per-MWh cost the trade is
all-or-nothing (full cycle when the spread clears 2·c_deg, idle otherwise), unlike
the retired convex-PWL model's partial optimum.
"""

import pytest

from bess.assets.battery import BatterySpec, DegradationSpec
from bess.optimizer.core import solve

TOL = 1e-6


def assert_list_close(actual, expected, tol=TOL):
    assert len(actual) == len(expected), f"length {len(actual)} != {len(expected)}"
    for i, (a, e) in enumerate(zip(actual, expected, strict=True)):
        assert a == pytest.approx(e, abs=tol), f"index {i}: {a} != {e}"


def test_oracle_1_cheap_wear_full_cycle():
    """Round-trip cost 2·c_deg=20 < spread 50 ⇒ full cycle; obj = 50 − 2·10 = 30."""
    deg = DegradationSpec(cost_per_mwh=10.0)
    spec = BatterySpec(eta_charge=1.0, eta_discharge=1.0, degradation=deg)
    s = solve([0.0, 50.0], spec, dt=1.0)

    assert s.objective == pytest.approx(30.0, abs=TOL)
    assert_list_close(s.p_charge, [1.0, 0.0])
    assert_list_close(s.p_discharge, [0.0, 1.0])
    assert_list_close(s.soc, [1.0, 0.0])


def test_oracle_2_expensive_wear_idle():
    """Round-trip cost 2·c_deg=60 > spread 50 ⇒ don't trade; obj 0. Breakeven c_deg=25."""
    deg = DegradationSpec(cost_per_mwh=30.0)
    spec = BatterySpec(eta_charge=1.0, eta_discharge=1.0, degradation=deg)
    s = solve([0.0, 50.0], spec, dt=1.0)

    assert s.objective == pytest.approx(0.0, abs=TOL)
    assert_list_close(s.p_charge, [0.0, 0.0])
    assert_list_close(s.p_discharge, [0.0, 0.0])
    assert_list_close(s.soc, [0.0, 0.0])


def test_oracle_3_storage_side():
    """η_dis=0.8: τ is cell-side (discharge τ = p_dis/η_dis = 1, not 0.8).

    f(q) = (40 − 2·c_deg)·q; at c_deg=10 the slope is 20 > 0 ⇒ q*=1, obj 20.
    A grid-side cost would score discharge throughput as p_dis=0.8 and give 22."""
    deg = DegradationSpec(cost_per_mwh=10.0)
    spec = BatterySpec(eta_charge=1.0, eta_discharge=0.8, degradation=deg)
    s = solve([0.0, 50.0], spec, dt=1.0)

    assert s.objective == pytest.approx(20.0, abs=TOL)
    assert_list_close(s.p_charge, [1.0, 0.0])
    assert_list_close(s.p_discharge, [0.0, 0.8])
    assert_list_close(s.soc, [1.0, 0.0])


def test_oracle_4_disabled_matches_r11():
    """degradation=None ⇒ exactly R1.1 oracle 1."""
    spec = BatterySpec(eta_charge=1.0, eta_discharge=1.0)  # degradation defaults None
    s = solve([10.0, 50.0, 20.0], spec, dt=1.0)

    assert s.objective == pytest.approx(40.0, abs=TOL)
    assert_list_close(s.p_charge, [1.0, 0.0, 0.0])
    assert_list_close(s.p_discharge, [0.0, 1.0, 0.0])
    assert_list_close(s.soc, [1.0, 0.0, 0.0])
