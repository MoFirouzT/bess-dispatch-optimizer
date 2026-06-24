"""Golden oracles — hand-solved exact values; the un-fakeable correctness gate.

Contract: docs/specs/R1.1-deterministic-core.md § "Golden oracles".
Math: docs/formulation.md § "R1.1 — Deterministic core".

All three use T=3, dt=1, a 1 MWh / 1 MW battery, e0 = e_tgt = 0, ramp disabled.
Tolerance 1e-6 (see the spec for why this value, not zero).
"""

import pytest

from bess.assets.battery import BatterySpec
from bess.optimizer.core import solve

TOL = 1e-6


def assert_list_close(actual, expected, tol=TOL):
    assert len(actual) == len(expected), f"length {len(actual)} != {len(expected)}"
    for i, (a, e) in enumerate(zip(actual, expected, strict=True)):
        assert a == pytest.approx(e, abs=tol), f"index {i}: {a} != {e}"


def test_oracle_1_lossless_arbitrage():
    """Buy low @10, sell high @50; idle @20. Direction + objective recompute."""
    spec = BatterySpec(eta_charge=1.0, eta_discharge=1.0)
    sched = solve([10.0, 50.0, 20.0], spec, dt=1.0)

    assert sched.objective == pytest.approx(40.0, abs=TOL)
    assert_list_close(sched.p_charge, [1.0, 0.0, 0.0])
    assert_list_close(sched.p_discharge, [0.0, 1.0, 0.0])
    assert_list_close(sched.soc, [1.0, 0.0, 0.0])


def test_oracle_2_grid_side_efficiency():
    """eta_ch = eta_dis = 0.95. Efficiency is grid-side (in the SoC balance):
    charge 1.0 -> store 0.95 -> discharge 0.9025 grid-side. Objective 35.125."""
    spec = BatterySpec(eta_charge=0.95, eta_discharge=0.95)
    sched = solve([10.0, 50.0, 20.0], spec, dt=1.0)

    assert sched.objective == pytest.approx(35.125, abs=TOL)
    assert_list_close(sched.p_charge, [1.0, 0.0, 0.0])
    assert_list_close(sched.p_discharge, [0.0, 0.9025, 0.0])
    assert_list_close(sched.soc, [0.95, 0.0, 0.0])


def test_oracle_3_declines_unprofitable_spread():
    """Best spread (buy@40/sell@42) is 5% < 1/eta_rt - 1 ≈ 10.8%; every trade
    loses money after round-trip losses, so the optimum is idle. Objective 0."""
    spec = BatterySpec(eta_charge=0.95, eta_discharge=0.95)
    sched = solve([40.0, 42.0, 41.0], spec, dt=1.0)

    assert sched.objective == pytest.approx(0.0, abs=TOL)
    assert_list_close(sched.p_charge, [0.0, 0.0, 0.0])
    assert_list_close(sched.p_discharge, [0.0, 0.0, 0.0])
    assert_list_close(sched.soc, [0.0, 0.0, 0.0])


def test_oracle_4_negative_prices_paid_load():
    """T=2, uniformly negative price. The battery profits as a *paid load*:
    paid 1.0 to charge 1 MWh, pays 0.9025 to discharge 0.9025 MWh, keeping the
    round-trip loss (0.0975 MWh) consumed at the negative price. Not phantom
    profit, and not the simultaneous charge+discharge the binary forbids."""
    spec = BatterySpec(eta_charge=0.95, eta_discharge=0.95)
    sched = solve([-1.0, -1.0], spec, dt=1.0)

    assert sched.objective == pytest.approx(0.0975, abs=TOL)
    assert_list_close(sched.p_charge, [1.0, 0.0])
    assert_list_close(sched.p_discharge, [0.0, 0.9025])
    assert_list_close(sched.soc, [0.95, 0.0])
