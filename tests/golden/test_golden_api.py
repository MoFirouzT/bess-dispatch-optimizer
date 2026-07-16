"""Golden oracles for the R1.5 dispatch HTTP service (FastAPI TestClient).

Contract: docs/specs/R1.5-serving.md § "Golden oracles". Pins the response schema
to the engine: the service returns exactly what solve() returns, invalid input is a
structured 422, and /health reports solver availability.
"""

import pytest
from fastapi.testclient import TestClient

from bess.api.app import app

client = TestClient(app)

# R1.1 oracle 1: 1 MWh / 1 MW, η=1, prices [10,50,20] -> objective 40, charge then discharge.
SPEC = {
    "capacity": 1.0,
    "soc_min": 0.0,
    "p_charge_max": 1.0,
    "p_discharge_max": 1.0,
    "eta_charge": 1.0,
    "eta_discharge": 1.0,
    "soc_initial": 0.0,
    "soc_terminal": 0.0,
}


def test_oracle_1_dispatch_optimal():
    body = {"prices_eur_mwh": [10.0, 50.0, 20.0], "dt_hours": 1.0, "battery": SPEC}
    r = client.post("/dispatch", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "optimal"
    assert data["solver_termination"] == "optimal"
    assert data["objective_eur"] == pytest.approx(40.0, abs=1e-6)
    assert data["schedule"]["p_charge_mw"] == pytest.approx([1.0, 0.0, 0.0], abs=1e-6)
    assert data["schedule"]["p_discharge_mw"] == pytest.approx([0.0, 1.0, 0.0], abs=1e-6)
    assert data["schedule"]["soc_mwh"] == pytest.approx([1.0, 0.0, 0.0], abs=1e-6)


def test_oracle_3_empty_horizon_is_422():
    body = {"prices_eur_mwh": [], "dt_hours": 1.0, "battery": SPEC}
    r = client.post("/dispatch", json=body)
    assert r.status_code == 422
    issues = r.json()["issues"]
    assert any(i["code"] == "empty_horizon" for i in issues)


def test_health_reports_solver():
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["solver_available"] is True


def _schedule_feasible(schedule: dict, spec: dict, dt: float, eps: float = 1e-6) -> bool:
    """The served schedule satisfies power caps, mutual exclusion, SoC bounds, exact
    continuity, and ends empty — checked straight off the HTTP response body."""
    e_min = spec["soc_min"] * spec["capacity"]
    pc, pdis, soc = schedule["p_charge_mw"], schedule["p_discharge_mw"], schedule["soc_mwh"]
    prev = e_min
    for t in range(len(pc)):
        if not (-eps <= pc[t] <= spec["p_charge_max"] + eps):
            return False
        if not (-eps <= pdis[t] <= spec["p_discharge_max"] + eps):
            return False
        if pc[t] > eps and pdis[t] > eps:
            return False
        if not (e_min - eps <= soc[t] <= spec["capacity"] + eps):
            return False
        expected = prev + spec["eta_charge"] * pc[t] * dt - pdis[t] / spec["eta_discharge"] * dt
        if abs(soc[t] - expected) > eps:
            return False
        prev = soc[t]
    return abs(prev - e_min) <= eps


# R2.4: the money instance (1 MW / 2 MWh, idle through the 100 spike, water value 100).
EXPLAIN_SPEC = {**SPEC, "capacity": 2.0}


def test_explain_returns_schedule_and_water_value():
    """POST /explain returns the optimal schedule plus per-period water values, bands,
    and breakeven slippage (R2.4 oracle 1, served over HTTP)."""
    body = {"prices_eur_mwh": [10.0, 100.0, 200.0], "dt_hours": 1.0, "battery": EXPLAIN_SPEC}
    r = client.post("/explain", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["objective_eur"] == pytest.approx(190.0, abs=1e-6)
    assert [p["action"] for p in data["periods"]] == ["charge", "idle", "discharge"]
    for p in data["periods"]:
        assert p["water_value_eur_mwh"] == pytest.approx(100.0, abs=1e-6)
        assert p["band_low_eur_mwh"] == pytest.approx(100.0, abs=1e-6)
    assert data["periods"][0]["breakeven_slippage_eur_mwh"] == pytest.approx(90.0, abs=1e-6)
    assert data["periods"][1]["breakeven_slippage_eur_mwh"] is None  # idle
    assert data["periods"][2]["breakeven_slippage_eur_mwh"] == pytest.approx(100.0, abs=1e-6)
    assert len(data["runs"]) == 1 and data["runs"][0]["pinned"] is True


def test_explain_invalid_input_is_422():
    """Invalid input is the shared pre-flight 422, not a 503 or a hollow 200."""
    body = {"prices_eur_mwh": [], "dt_hours": 1.0, "battery": EXPLAIN_SPEC}
    r = client.post("/explain", json=body)
    assert r.status_code == 422
    assert any(i["code"] == "empty_horizon" for i in r.json()["issues"])


def test_explain_solve_failure_is_503(monkeypatch):
    """A solve that does not reach optimality is a 503 (decision 5): no faithful
    explanation, and never a greedy fallback (which has no duals)."""
    from bess.api import app as app_module

    def _boom(*_args, **_kwargs):
        raise RuntimeError("solve did not reach optimality")

    monkeypatch.setattr(app_module, "explain_schedule", _boom)
    body = {"prices_eur_mwh": [10.0, 100.0, 200.0], "dt_hours": 1.0, "battery": EXPLAIN_SPEC}
    r = client.post("/explain", json=body)
    assert r.status_code == 503


def test_breaker_trips_via_http_returns_feasible_fallback(monkeypatch):
    """Master-plan R1.5 gate: under stress the breaker trips and the API still returns
    a constraint-satisfying schedule. Force a tiny latency budget so the wall-clock
    guard degrades to greedy, exercised end-to-end through the FastAPI app."""
    from bess.api import app as app_module

    monkeypatch.setattr(app_module.settings, "latency_budget_seconds", 1e-9)
    body = {"prices_eur_mwh": [10.0, 50.0, 20.0], "dt_hours": 1.0, "battery": SPEC}
    r = client.post("/dispatch", json=body)

    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "fallback_greedy"
    assert data["solver_termination"] == "fallback"
    assert _schedule_feasible(data["schedule"], SPEC, 1.0)
