"""Unit gates for R2.4b — the adversarial claim set and every fallback trigger.

Contract: docs/specs/dual-narration.md § "Rejection rules", § "Acceptance gate".

One case per rejection rule, each rejected. Nothing here opens a socket: the provider
is injected, and the credential-absent path is exercised with the environment cleared.
"""

import pytest

from bess.assets.battery import BatterySpec
from bess.explain.duals import explain_schedule
from bess.narrate.claims import Claim, Narration
from bess.narrate.narrate import (
    CREDENTIAL_ENV,
    NarrationConfig,
    build_prompt,
    narrate,
)
from bess.narrate.provider import MalformedProvider, RaisingProvider, RecordedProvider
from bess.narrate.render import fallback
from bess.narrate.verify import verify

SPEC = BatterySpec(
    capacity=2.0,
    p_charge_max=1.0,
    p_discharge_max=1.0,
    eta_charge=1.0,
    eta_discharge=1.0,
    soc_initial=0.0,
    soc_terminal=0.0,
)


@pytest.fixture(scope="module")
def exp():
    return explain_schedule([10.0, 100.0, 200.0], SPEC, dt=1.0)


def _one(claim: Claim) -> Narration:
    return Narration(claims=[claim])


ADVERSARIAL = {
    "digit_in_text": _one(Claim(type="threshold_cross", refs=[0], text="It charged at 10.00 EUR.")),
    "unknown_type": Narration.model_construct(
        claims=[Claim.model_construct(type="invented", refs=[0], text="Anything.")]
    ),
    "bad_refs": _one(Claim(type="threshold_cross", refs=[99], text="It charged.")),
    "predicate_failed": _one(
        Claim(type="threshold_cross", refs=[1], text="It charged at {price:1}.")
    ),
    "foreign_placeholder": _one(
        Claim(type="threshold_cross", refs=[0], text="It charged at {price:2}.")
    ),
    "unresolvable_placeholder": _one(
        Claim(type="no_trade_band", refs=[1], text="It held, leaving {slippage:1}.")
    ),
    "claim_count": Narration(claims=[]),
}


@pytest.mark.parametrize("rule", sorted(ADVERSARIAL))
def test_every_rejection_rule_fires(rule, exp):
    """The seeded adversarial set covers each rule, and every member is rejected."""
    assert verify(ADVERSARIAL[rule], exp) == rule


def test_wrong_arity_is_a_bad_ref(exp):
    """Rule 3 covers arity as well as bounds: a run step needs two indices."""
    assert verify(_one(Claim(type="water_value_step", refs=[0], text="It stepped.")), exp) == (
        "bad_refs"
    )


def test_too_many_claims_is_rejected(exp):
    ok = Claim(type="threshold_cross", refs=[0], text="It charged at {price:0}.")
    assert verify(Narration(claims=[ok] * 9), exp, max_claims=8) == "claim_count"


def test_a_verified_narration_is_served(exp):
    """The accepting path: a valid claim list renders and reports verified."""
    narration = _one(Claim(type="threshold_cross", refs=[0], text="It charged at {price:0}."))
    result = narrate(exp, config=NarrationConfig(), provider=RecordedProvider(narration))
    assert result.verified is True
    assert result.rejection is None
    assert result.text == "It charged at 10.00."


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        (RaisingProvider(RuntimeError("transport")), "provider_error: RuntimeError"),
        (RaisingProvider(TimeoutError("slow")), "provider_error: TimeoutError"),
        (MalformedProvider(), "provider_error: ValueError"),
    ],
)
def test_provider_failures_fall_back(provider, expected, exp):
    result = narrate(exp, config=NarrationConfig(), provider=provider)
    assert (result.verified, result.rejection) == (False, expected)
    assert result.text == fallback(exp)


def test_no_credential_falls_back_without_constructing_a_client(exp, monkeypatch):
    """How CI runs the whole path: no key, no network, no client.

    The SDK is an optional extra, so constructing a client here would fail the suite
    on an install that never asked for it.
    """
    monkeypatch.delenv(CREDENTIAL_ENV, raising=False)
    result = narrate(exp)
    assert (result.verified, result.rejection) == (False, "no_credential")
    assert result.text == fallback(exp)


def test_the_prompt_states_the_digit_rule_and_carries_the_solved_facts(exp):
    """The prompt is the model's only substrate, and the constraint is stated in it."""
    prompt = build_prompt(exp, NarrationConfig())
    assert "must not write any digit" in prompt
    assert "{price:t}" in prompt
    assert '"water_value_eur_mwh": 100.0' in prompt


def test_the_config_defaults_match_the_spec():
    config = NarrationConfig()
    assert (config.model, config.effort, config.max_claims) == ("claude-opus-5", "low", 8)


def test_the_narrative_endpoint_serves_the_fallback_without_a_credential(monkeypatch):
    """`/explain/narrative` is a 200 with `verified=False`, never an error (R2.4b).

    The R1.5 breaker returns a 503 on `/explain` because its fallback would be a worse
    *schedule*. Here the fallback is the same facts in duller words, so the endpoint
    serves it and says so in the body.
    """
    from fastapi.testclient import TestClient

    from bess.api.app import app

    monkeypatch.delenv(CREDENTIAL_ENV, raising=False)
    body = {
        "prices_eur_mwh": [10.0, 100.0, 200.0],
        "dt_hours": 1.0,
        "battery": SPEC.model_dump(),
    }
    response = TestClient(app).post("/explain/narrative", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data["verified"] is False
    assert data["rejection"] == "no_credential"
    assert data["narrative"].startswith("Generated narration was unavailable")
    # The explanation half of the body is `/explain`'s, unchanged.
    assert data["objective_eur"] == pytest.approx(190.0, abs=1e-6)
    assert [p["action"] for p in data["periods"]] == ["charge", "idle", "discharge"]


def test_the_narrative_endpoint_keeps_the_explain_failure_codes(monkeypatch):
    """A solve failure is still a 503: only *narration* failures fall back."""
    from fastapi.testclient import TestClient

    from bess.api import app as app_module

    def _boom(*args, **kwargs):
        raise RuntimeError("solver missed optimality")

    monkeypatch.setattr(app_module, "explain_schedule", _boom)
    body = {
        "prices_eur_mwh": [10.0, 100.0, 200.0],
        "dt_hours": 1.0,
        "battery": SPEC.model_dump(),
    }
    response = TestClient(app_module.app).post("/explain/narrative", json=body)
    assert response.status_code == 503
