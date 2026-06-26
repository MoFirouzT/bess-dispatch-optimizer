"""Golden oracles for the pre-flight validator — exact expected issue lists.

Contract: docs/specs/R1.3-validation.md § "Golden oracles".
Math: docs/formulation.md § "R1.3 — Pre-flight feasibility (derived; no new model)".

Pre-flight is pure, so each case pins an exact set of issue codes (and, for the
reachability cases, the offending field + the machine-readable context numbers).
Defaults are the 1 MWh / 1 MW spec, dt=1, unless the case overrides them.
"""

import math

import pytest

from bess.assets.battery import BatterySpec
from bess.validation.preflight import IssueCode, validate

TOL = 1e-6


def codes(issues):
    return [i.code for i in issues]


def test_oracle_1_clean_input_passes():
    """Good input (R1.1 oracle 1) produces no issues — pre-flight never blocks a
    valid solve."""
    spec = BatterySpec(eta_charge=1.0, eta_discharge=1.0)  # e_0 = e_tgt = 0
    assert validate([10.0, 50.0, 20.0], spec, dt=1.0) == []


def test_oracle_2_empty_horizon():
    spec = BatterySpec()
    assert codes(validate([], spec, dt=1.0)) == [IssueCode.EMPTY_HORIZON]


def test_oracle_3_non_finite_price_with_index():
    spec = BatterySpec()
    issues = validate([10.0, math.nan, 20.0], spec, dt=1.0)
    assert codes(issues) == [IssueCode.NON_FINITE_PRICE]
    assert issues[0].field == "prices[1]"


def test_oracle_4_non_positive_dt():
    spec = BatterySpec()
    assert codes(validate([10.0, 50.0], spec, dt=0.0)) == [IssueCode.NON_POSITIVE_DT]


def test_oracle_5_terminal_unreachable_charge():
    """Need +1.0 MWh in one period; max charge is eta_ch*P_ch*dt = 1*0.5*1 = 0.5."""
    spec = BatterySpec(soc_initial=0.0, soc_terminal=1.0, p_charge_max=0.5, eta_charge=1.0)
    issues = validate([50.0], spec, dt=1.0)
    assert codes(issues) == [IssueCode.TERMINAL_UNREACHABLE_CHARGE]
    assert issues[0].field == "soc_terminal"
    assert issues[0].context["required"] == pytest.approx(1.0, abs=TOL)
    assert issues[0].context["reachable"] == pytest.approx(0.5, abs=TOL)
    assert issues[0].context["horizon"] == 1


def test_oracle_6_terminal_unreachable_discharge():
    """Need -1.0 MWh in one period; max removal is P_dis*dt/eta_dis = 0.5*1/1 = 0.5."""
    spec = BatterySpec(soc_initial=1.0, soc_terminal=0.0, p_discharge_max=0.5, eta_discharge=1.0)
    issues = validate([50.0], spec, dt=1.0)
    assert codes(issues) == [IssueCode.TERMINAL_UNREACHABLE_DISCHARGE]
    assert issues[0].field == "soc_terminal"
    assert issues[0].context["required"] == pytest.approx(1.0, abs=TOL)
    assert issues[0].context["reachable"] == pytest.approx(0.5, abs=TOL)


def test_oracle_7_reachable_at_the_boundary():
    """Two periods reach exactly 2*0.5 = 1.0 = required — equality is feasible."""
    spec = BatterySpec(soc_initial=0.0, soc_terminal=1.0, p_charge_max=0.5, eta_charge=1.0)
    assert validate([50.0, 50.0], spec, dt=1.0) == []


def test_oracle_8_issues_accumulate():
    """One call reports every problem (no fail-fast); order is dt then prices."""
    spec = BatterySpec()
    issues = validate([10.0, math.inf], spec, dt=0.0)
    assert codes(issues) == [IssueCode.NON_POSITIVE_DT, IssueCode.NON_FINITE_PRICE]
