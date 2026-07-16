"""Golden oracles for R2.4 — shadow-price explainability.

Contract: docs/specs/R2.4-explainability.md § "Golden oracles".
Math: docs/formulation.md § "R2.4. Shadow-price explainability".
Decision: docs/decisions/0023-milp-dual-resolve-rule.md.

The water value is the SoC-balance dual, read off the solved R1.1/R1.2 dispatch by
fix-and-resolve. Oracle 1 is the load-bearing case: three re-solve rules return the
same objective (190) but different water values (200/100/10), and only the shipped
rule recovers the true dV/de_0 = 100. All values hand-computed, locked at 1e-6.

Failing until `bess.explain.duals` is implemented (test-first, R2.4 build task).
"""

import pyomo.environ as pyo
import pytest

from bess.assets.battery import BatterySpec, DegradationSpec
from bess.explain.duals import DualityError, explain_schedule
from bess.optimizer.core import _HIGHS_TOLERANCES, build_model

TOL = 1e-6


def run_of(exp, t):
    """The FlatRun that period t belongs to."""
    return exp.runs[exp.periods[t].run]


def _resolve_idle_rule(prices, spec, idle_rule):
    """Re-solve the fixed-commitment LP under one idle rule, return (objective, duals).

    Reproduces the three candidate rules of ADR-0023 on a schedule that charges,
    idles, discharges. Trading periods fix ``u`` by direction; the idle period differs:
    ``fix_u`` keeps u=0, ``fix_zero`` also clamps its power to zero, ``free_idle``
    relaxes both exclusion caps to the natural power caps.
    """
    m = build_model(prices, spec, 1.0)
    m.u.domain = pyo.Reals
    for t in m.T:
        if t == 0:  # charge
            m.u[t].fix(1.0)
        elif t == 2:  # discharge
            m.u[t].fix(0.0)
        else:  # idle
            if idle_rule == "free_idle":
                m.charge_limit[t].deactivate()
                m.discharge_limit[t].deactivate()
                m.p_charge[t].setub(spec.p_charge_max)
                m.p_discharge[t].setub(spec.p_discharge_max)
                m.u[t].fix(0.0)
            elif idle_rule == "fix_zero":
                m.u[t].fix(0.0)
                m.p_charge[t].fix(0.0)
                m.p_discharge[t].fix(0.0)
            else:  # fix_u
                m.u[t].fix(0.0)
    m.dual = pyo.Suffix(direction=pyo.Suffix.IMPORT)
    opt = pyo.SolverFactory("appsi_highs")
    for key, val in _HIGHS_TOLERANCES.items():
        opt.options[key] = val
    opt.solve(m)
    return pyo.value(m.revenue), [m.dual[m.soc_balance[t]] for t in sorted(m.T)]


def test_the_three_idle_rules_disagree_at_one_objective():
    """ADR-0023's load-bearing measurement, pinned in executable form.

    On oracle 1's instance the three re-solve rules return the *same* objective (190)
    but water values of 200 / 100 / 10; only free_idle recovers the true dV/de_0 = 100.
    This is why oracle 1 gates the rule choice, and why objective equality alone cannot.
    """
    spec = BatterySpec(capacity=2.0, eta_charge=1.0, eta_discharge=1.0)
    prices = [10.0, 100.0, 200.0]
    expected_mu = {"fix_u": 200.0, "free_idle": 100.0, "fix_zero": 10.0}
    for rule, mu in expected_mu.items():
        obj, duals = _resolve_idle_rule(prices, spec, rule)
        assert obj == pytest.approx(190.0, abs=TOL), f"{rule} objective moved"
        assert duals == pytest.approx([mu, mu, mu], abs=TOL), f"{rule} water value"
    # The shipped rule is free_idle: it matches the finite-difference truth, 100.
    assert explain_schedule(prices, spec, dt=1.0).periods[0].water_value_eur_mwh == pytest.approx(
        100.0, abs=TOL
    )


def test_oracle_1_water_value_recovers_dv_de0():
    """T=3, pi=[10,100,200], 1 MW / 2 MWh, idle through the 100 spike.

    The money case. The MILP charges, idles, discharges (obj 190); the water value
    is a flat 100 = dV/de_0 (a marginal stored MWh clears at t2, not t3 where power
    is capped). fix_u and fix_zero would report 200 and 10 at the same objective, so
    this instance is the only gate that separates the idle rules.
    """
    spec = BatterySpec(capacity=2.0, eta_charge=1.0, eta_discharge=1.0)
    exp = explain_schedule([10.0, 100.0, 200.0], spec, dt=1.0)

    assert exp.schedule.objective == pytest.approx(190.0, abs=TOL)
    assert [p.action for p in exp.periods] == ["charge", "idle", "discharge"]
    for p in exp.periods:
        assert p.water_value_eur_mwh == pytest.approx(100.0, abs=TOL)

    # No fallback (no negative-priced idle), so the whole run is pinned and bands
    # are reported everywhere. At eta=1, c_deg=0 the band collapses to the point mu.
    assert len(exp.runs) == 1
    assert exp.runs[0].pinned is True
    assert exp.runs[0].periods == (0, 1, 2)
    for p in exp.periods:
        assert p.band_low_eur_mwh == pytest.approx(100.0, abs=TOL)
        assert p.band_high_eur_mwh == pytest.approx(100.0, abs=TOL)

    # Breakeven slippage: 100-10 at the charge, 200-100 at the discharge, None idle.
    assert exp.periods[0].breakeven_slippage_eur_mwh == pytest.approx(90.0, abs=TOL)
    assert exp.periods[1].breakeven_slippage_eur_mwh is None
    assert exp.periods[2].breakeven_slippage_eur_mwh == pytest.approx(100.0, abs=TOL)


def test_oracle_2_fix_and_resolve_sound_on_canonical():
    """R1.1 worked example: the re-solved LP objective equals the MILP's, 40.

    Pins fix-and-resolve soundness (no DualityError) on the canonical instance.
    """
    spec = BatterySpec(capacity=1.0, eta_charge=1.0, eta_discharge=1.0)
    exp = explain_schedule([10.0, 50.0, 20.0], spec, dt=1.0)  # must not raise
    assert exp.schedule.objective == pytest.approx(40.0, abs=TOL)


def test_oracle_3_round_trip_loss_creates_the_band():
    """An idle period at eta=0.9 has a band of positive width; at eta=1 it collapses.

    Same instance ([10,120,130], 1 MWh), idle at t1 (holds for the 130 later). The
    band width is created by round-trip loss, not the price.
    """
    lossy = BatterySpec(capacity=1.0, eta_charge=0.9, eta_discharge=0.9)
    exp = explain_schedule([10.0, 120.0, 130.0], lossy, dt=1.0)
    assert exp.periods[1].action == "idle"
    lo, hi = exp.periods[1].band_low_eur_mwh, exp.periods[1].band_high_eur_mwh
    # mu = 117 (interior SoC), band [0.9*117, 117/0.9] = [105.3, 130.0], width 24.7.
    assert lo == pytest.approx(105.3, abs=TOL)
    assert hi == pytest.approx(130.0, abs=TOL)
    assert lo - TOL <= 120.0 <= hi + TOL  # the idle price sits inside its band

    lossless = BatterySpec(capacity=1.0, eta_charge=1.0, eta_discharge=1.0)
    exp1 = explain_schedule([10.0, 120.0, 130.0], lossless, dt=1.0)
    assert exp1.periods[1].action == "idle"
    # At eta=1, c_deg=0 the band is [mu, mu] by construction: width exactly 0.
    width = exp1.periods[1].band_high_eur_mwh - exp1.periods[1].band_low_eur_mwh
    assert width == pytest.approx(0.0, abs=TOL)


def test_oracle_4_degradation_surfaced_and_widens_the_band():
    """Oracle 1's instance with c_deg=15: per-period D_t and a wear-widened band.

    Pins the R1.2-deferred per-period cost and degradation's effect on the band.
    """
    spec = BatterySpec(
        capacity=2.0,
        eta_charge=1.0,
        eta_discharge=1.0,
        degradation=DegradationSpec(cost_per_mwh=15.0),
    )
    exp = explain_schedule([10.0, 100.0, 200.0], spec, dt=1.0)

    assert exp.schedule.objective == pytest.approx(160.0, abs=TOL)  # 190 gross - 30 wear
    for p in exp.periods:
        assert p.water_value_eur_mwh == pytest.approx(85.0, abs=TOL)  # 100 - c_deg
    # D_t = c_deg * tau_t: 15 at the full-power charge and discharge, 0 idle.
    assert [p.degradation_cost_eur for p in exp.periods] == [
        pytest.approx(15.0, abs=TOL),
        pytest.approx(0.0, abs=TOL),
        pytest.approx(15.0, abs=TOL),
    ]
    # Band widens from oracle 1's zero width to [70, 100] (width 2*c_deg = 30).
    for p in exp.periods:
        assert p.band_low_eur_mwh == pytest.approx(70.0, abs=TOL)
        assert p.band_high_eur_mwh == pytest.approx(100.0, abs=TOL)
    assert exp.periods[0].breakeven_slippage_eur_mwh == pytest.approx(60.0, abs=TOL)
    assert exp.periods[2].breakeven_slippage_eur_mwh == pytest.approx(100.0, abs=TOL)


def test_oracle_5_shipped_rule_reproduces_milp_at_negative_idle():
    """A lossy instance idling at a negative price: the shipped rule stays sound.

    pi=[-50,100,-50], eta=0.9: the MILP charges, discharges, then IDLES at t2 (pi=-50,
    a fallback period). The shipped rule (u* kept at pi<0 idle) reproduces the MILP
    objective 131. An UNRESTRICTED relaxation would dump a SoC-neutral round trip the
    market pays for and report 140.5 (excess 9.5 = 50*(1-0.81)); the objective-equality
    guard is what forbids that, and this oracle pins that the shipped path does not.
    """
    spec = BatterySpec(
        capacity=2.0,
        eta_charge=0.9,
        eta_discharge=0.9,
        soc_initial=0.0,
        soc_terminal=0.0,
    )
    exp = explain_schedule([-50.0, 100.0, -50.0], spec, dt=1.0)  # must not raise
    assert exp.schedule.objective == pytest.approx(131.0, abs=TOL)
    assert exp.periods[2].action == "idle"
    assert exp.periods[2].price_eur_mwh == pytest.approx(-50.0, abs=TOL)


def test_oracle_6_fallback_band_reported_iff_run_pinned():
    """A negative-priced idle period reports a band iff its flat run is pinned.

    Pinned case: pi=[-10,-10,-40,20,20], eta=0.9, c_deg=8, soc=0.3; t0 idles at pi=-10
    inside a run pinned by a later interior trade, so its band is reported and brackets
    the price. Unpinned case: pi=[130,-40,-40,-10,70]; t3 idles at pi=-10 in a run the
    two tie-breaks disagree on, so the band is suppressed while mu is still reported.
    """
    pinned_spec = BatterySpec(
        capacity=1.5,
        eta_charge=0.9,
        eta_discharge=0.9,
        soc_initial=0.3,
        soc_terminal=0.3,
        degradation=DegradationSpec(cost_per_mwh=8.0),
    )
    exp_p = explain_schedule([-10.0, -10.0, -40.0, 20.0, 20.0], pinned_spec, dt=1.0)
    p0 = exp_p.periods[0]
    assert p0.action == "idle" and p0.price_eur_mwh == pytest.approx(-10.0, abs=TOL)
    assert run_of(exp_p, 0).pinned is True
    assert p0.band_low_eur_mwh is not None and p0.band_high_eur_mwh is not None
    assert p0.band_low_eur_mwh - TOL <= -10.0 <= p0.band_high_eur_mwh + TOL

    unpinned_spec = BatterySpec(
        capacity=1.5,
        eta_charge=0.9,
        eta_discharge=0.9,
        soc_initial=0.3,
        soc_terminal=0.3,
    )
    exp_u = explain_schedule([130.0, -40.0, -40.0, -10.0, 70.0], unpinned_spec, dt=1.0)
    p3 = exp_u.periods[3]
    assert p3.action == "idle" and p3.price_eur_mwh == pytest.approx(-10.0, abs=TOL)
    assert run_of(exp_u, 3).pinned is False
    assert p3.band_low_eur_mwh is None and p3.band_high_eur_mwh is None
    assert p3.water_value_eur_mwh is not None  # mu still reported, band suppressed


def test_oracle_7_breakeven_slippage_read_off():
    """Per-trade breakeven slippage on oracle 1's schedule: pure arithmetic on duals.

    Charge at pi=10 clears its threshold by 100-10=90; discharge at pi=200 by
    200-100=100. Both >= 0 by optimality; no re-solve, no objective term.
    """
    spec = BatterySpec(capacity=2.0, eta_charge=1.0, eta_discharge=1.0)
    exp = explain_schedule([10.0, 100.0, 200.0], spec, dt=1.0)
    assert exp.periods[0].breakeven_slippage_eur_mwh == pytest.approx(90.0, abs=TOL)
    assert exp.periods[2].breakeven_slippage_eur_mwh == pytest.approx(100.0, abs=TOL)
    for p in exp.periods:
        if p.action != "idle":
            assert p.breakeven_slippage_eur_mwh >= -TOL


def test_duality_error_is_exported():
    """The guard's exception type is part of the public surface (raised on a
    re-solved objective that does not match the MILP; see the soundness property)."""
    assert issubclass(DualityError, Exception)
