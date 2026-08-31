"""Golden oracles for R2.4b — dual-grounded narration.

Contract: docs/specs/dual-narration.md § "Golden oracles".

The instance is R2.4's own oracle 1 (docs/formulation.md § R2.4, worked example):
T=3, pi=[10,100,200] on a 1 MW / 2 MWh asset at eta=1 with no wear. It solves to
objective 190 with a single pinned flat run at mu=100, and per-trade breakeven
slippage 90 at the charge and 100 at the discharge. Every number below is that
solve's, so a change to the dual rule breaks these oracles as loudly as it breaks
R2.4's own.

Oracles 2-4 pin the rejection path: the rendered output must be the fallback,
verbatim, and never a partially-trusted narrative.

Failing until `bess.narrate` is implemented (test-first, R2.4b build task).
"""

import pytest

from bess.assets.battery import BatterySpec
from bess.explain.duals import explain_schedule
from bess.narrate.claims import Claim, Narration
from bess.narrate.render import fallback, render
from bess.narrate.verify import verify

ORACLE_1_SPEC = BatterySpec(
    capacity=2.0,
    p_charge_max=1.0,
    p_discharge_max=1.0,
    eta_charge=1.0,
    eta_discharge=1.0,
    soc_initial=0.0,
    soc_terminal=0.0,
)


@pytest.fixture(scope="module")
def oracle_1():
    return explain_schedule([10.0, 100.0, 200.0], ORACLE_1_SPEC, dt=1.0)


def test_oracle_1_the_explanation_is_the_one_r24_pins(oracle_1):
    """Guard: these oracles are only meaningful on R2.4's oracle-1 duals."""
    assert oracle_1.schedule.objective == pytest.approx(190.0, abs=1e-6)
    assert len(oracle_1.runs) == 1
    assert oracle_1.runs[0].water_value_eur_mwh == pytest.approx(100.0, abs=1e-6)
    assert oracle_1.runs[0].pinned
    assert oracle_1.periods[0].breakeven_slippage_eur_mwh == pytest.approx(90.0, abs=1e-6)
    assert oracle_1.periods[2].breakeven_slippage_eur_mwh == pytest.approx(100.0, abs=1e-6)


def test_oracle_1_substitution_is_exact(oracle_1):
    """Oracle 1: three valid claims render to one exact string.

    Pins the substitution arithmetic and the 2-dp formatting. No model is involved:
    the claim list is the fixture.
    """
    narration = Narration(
        claims=[
            Claim(
                type="threshold_cross",
                refs=[0],
                text="At {time:0} the price of {price:0} sat below the charge threshold "
                "of {band_low:0}, so the battery charged.",
            ),
            Claim(
                type="no_trade_band",
                refs=[1],
                text="At {time:1} the price of {price:1} was inside the no-trade band, so it held.",
            ),
            Claim(
                type="slippage_margin",
                refs=[2],
                text="The discharge at {time:2} clears its threshold by {slippage:2} "
                "before it would flip.",
            ),
        ]
    )
    assert verify(narration, oracle_1) is None
    assert render(narration, oracle_1) == (
        "At period 0 the price of 10.00 sat below the charge threshold of 100.00, "
        "so the battery charged. "
        "At period 1 the price of 100.00 was inside the no-trade band, so it held. "
        "The discharge at period 2 clears its threshold by 100.00 before it would flip."
    )


def test_oracle_2_a_literal_digit_is_rejected(oracle_1):
    """Rule 1, the rule the whole design rests on: no digit outside a placeholder."""
    narration = Narration(
        claims=[
            Claim(
                type="threshold_cross",
                refs=[0],
                text="The battery charged at a price of 10.00.",
            )
        ]
    )
    assert verify(narration, oracle_1) == "digit_in_text"


def test_oracle_3_a_band_claim_on_an_unpinned_run_is_rejected():
    """A negative-priced idle period can leave its run unpinned; no band may be asserted.

    Instance found by search rather than by hand: pinnedness needs the two idle
    tie-breaks to disagree, which takes a round-trip loss and a negative price
    together (docs/decisions/milp-dual-resolve-rule.md).
    """
    spec = BatterySpec(
        capacity=1.18,
        p_charge_max=1.97,
        p_discharge_max=1.24,
        eta_charge=0.85,
        eta_discharge=0.85,
        soc_initial=0.3,
        soc_terminal=0.3,
    )
    exp = explain_schedule([-55.3, -48.1, 50.5, 64.7], spec, dt=1.0)
    unpinned = [i for i, r in enumerate(exp.runs) if not r.pinned]
    assert unpinned, "fixture must produce an unpinned run"
    t = exp.runs[unpinned[0]].periods[0]
    narration = Narration(
        claims=[
            Claim(
                type="no_trade_band",
                refs=[t],
                text=f"It held at {{time:{t}}} with the price at {{price:{t}}}.",
            )
        ]
    )
    assert verify(narration, exp) == "predicate_failed"


def test_oracle_4_a_foreign_placeholder_is_rejected(oracle_1):
    """Rule 5: a claim about period 0 may not quote period 2's price."""
    narration = Narration(
        claims=[
            Claim(
                type="threshold_cross",
                refs=[0],
                text="The battery charged at {price:2}.",
            )
        ]
    )
    assert verify(narration, oracle_1) == "foreign_placeholder"


def test_the_fallback_string_is_pinned(oracle_1):
    """The fallback names itself and carries the deterministic reason strings."""
    assert fallback(oracle_1) == (
        "Generated narration was unavailable or failed verification, so this is the "
        "deterministic summary.\n"
        "Objective 190.00 EUR.\n"
        "Period 0: charge: price 10.00 at or below the charge threshold 100.00\n"
        "Period 1: idle: price 100.00 inside the no-trade band [100.00, 100.00]\n"
        "Period 2: discharge: price 200.00 at or above the discharge threshold 100.00"
    )
