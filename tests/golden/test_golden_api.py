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
