"""Integration — R2.3 stochastic layer on real ENTSO-E day-ahead prices.

Contract: docs/specs/R2.3-stochastic-recourse.md § "Acceptance gate" (integration).
Token-gated: skipped unless `ENTSOE_API_TOKEN` is set (never runs in CI). Nothing
fetched here is committed — real prices are pulled at runtime and discarded.

An empirical scenario set is built by treating each real NL day as one equiprobable
price-path scenario (a historical distribution over day shapes). What it proves on
*real* prices:
  (a) the decision-value ordering EEV ≤ RP ≤ WS and VSS ≥ 0, EVPI ≥ 0 survive real
      volatility (the structural guarantees of formulation §R2.3);
  (b) the CVaR-averse solution does not increase downside vs. the risk-neutral one.

Network setup (this machine): a TLS-intercepting proxy means uv-Python needs the
Keychain roots — see docs/specs/R1.4b-entsoe-loader.md § "Environment note".
"""

import os

import numpy as np
import pandas as pd
import pytest

from bess.assets.battery import BatterySpec
from bess.data.entsoe import fetch_day_ahead
from bess.scenarios import ScenarioSet
from bess.stochastic import solve_stochastic, value_of_stochastic_solution

pytestmark = pytest.mark.integration

requires_token = pytest.mark.skipif(
    not os.environ.get("ENTSOE_API_TOKEN"),
    reason="ENTSOE_API_TOKEN not set — live ENTSO-E integration test skipped (never runs in CI)",
)

TOL = 1e-6


def _daily_scenarios(prices: pd.Series, n_days: int) -> ScenarioSet:
    """Reshape a real hourly series into ``n_days`` equiprobable 24-hour paths."""
    values = prices.to_numpy(dtype=float)
    usable = (len(values) // 24) * 24
    paths = values[:usable].reshape(-1, 24)[:n_days]
    index = pd.date_range("2026-01-01", periods=24, freq="h", tz="UTC")
    return ScenarioSet(paths=paths, probs=np.full(len(paths), 1.0 / len(paths)), index=index)


@requires_token
def test_stochastic_invariants_on_real_prices():
    prices = fetch_day_ahead(
        "NL", pd.Timestamp("2024-06-01", tz="UTC"), pd.Timestamp("2024-06-15", tz="UTC")
    )
    scen = _daily_scenarios(prices, n_days=14)
    spec = BatterySpec()  # 1 MWh / 1 MW, η=0.95

    res = value_of_stochastic_solution(scen, spec, rho=0.5)
    # The decision-value ordering and non-negativity survive real volatility.
    assert res.eev <= res.rp + TOL
    assert res.rp <= res.ws + TOL
    assert res.vss >= -TOL
    assert res.evpi >= -TOL

    # Risk aversion does not worsen downside on real prices.
    neutral = solve_stochastic(scen, spec, alpha=0.9, lambda_=0.0, rho=0.5)
    averse = solve_stochastic(scen, spec, alpha=0.9, lambda_=0.9, rho=0.5)
    assert averse.cvar <= neutral.cvar + 1e-3
