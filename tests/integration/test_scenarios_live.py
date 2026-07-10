"""Integration — R2.2 scenario generation + reduction on real ENTSO-E prices.

Contract: docs/specs/R2.2-scenarios.md § "Acceptance gate" (token-gated
integration): generate + reduce on real ENTSO-E data and assert the trade-off
curve shape holds. Token-gated: skipped unless `ENTSOE_API_TOKEN` is set;
deselected in CI via the `integration` marker. Nothing fetched here is committed.

Generation is the residual-path bootstrap (ADR-0017): the "point forecast" is the
mean real day shape and the residual history is each real day's deviation from it,
so the generated paths are driven by genuine ENTSO-E intra-day error structure (no
forecast group needed — `generate_scenarios` only reads `forecast.point`). What it
proves on *real* prices:
  (a) forward selection preserves a valid probability measure over genuine original
      atoms; and
  (b) the reduction trade-off curve is monotone — the Kantorovich distance to the
      full set is non-increasing as the reduced count grows, and zero at full size.

Network setup (this machine): a TLS-intercepting proxy means uv-Python may need the
Keychain roots — see docs/specs/R1.4b-entsoe-loader.md § "Environment note".
"""

import os
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from bess.data.entsoe import fetch_day_ahead
from bess.scenarios import generate_scenarios, kantorovich_distance, reduce_scenarios

pytestmark = pytest.mark.integration

requires_token = pytest.mark.skipif(
    not os.environ.get("ENTSOE_API_TOKEN"),
    reason="ENTSOE_API_TOKEN not set — live ENTSO-E integration test skipped (never runs in CI)",
)


@requires_token
def test_generate_and_reduce_trade_off_on_real_prices():
    # One real month of NL hourly day-ahead prices → real day shapes. Never committed.
    prices = fetch_day_ahead(
        "NL", pd.Timestamp("2024-05-01", tz="UTC"), pd.Timestamp("2024-06-01", tz="UTC")
    )
    values = prices.to_numpy(dtype=float)
    usable = (len(values) // 24) * 24
    days = values[:usable].reshape(-1, 24)  # (M, 24) genuine day shapes
    index = pd.date_range("2026-01-01", periods=24, freq="h", tz="UTC")

    # Residual-path bootstrap driven by real data: μ̂ = mean day, residuals = each
    # real day minus μ̂ (the whole-day error vectors ADR-0017 resamples).
    point = pd.Series(days.mean(axis=0), index=index, name="price_eur_mwh")
    residuals = days - point.to_numpy()
    forecast = SimpleNamespace(point=point)  # generate_scenarios only reads `.point`

    scen = generate_scenarios(forecast, residuals, n=200, seed=0)
    assert scen.n_scenarios == 200
    assert scen.horizon == 24

    # Reduce at increasing sizes; the trade-off curve must be monotone.
    ks = [5, 10, 20, 40]
    distances: list[float] = []
    for k in ks:
        reduced, d = reduce_scenarios(scen, n_reduced=k, method="forward")

        # (a) a valid probability measure over genuine original atoms.
        assert reduced.n_scenarios == k
        assert np.isclose(reduced.probs.sum(), 1.0)
        assert (reduced.probs >= -1e-9).all()
        for kept_path in reduced.paths:
            assert np.any(np.all(np.isclose(scen.paths, kept_path), axis=1)), (
                "a kept path is not one of the original generated atoms"
            )

        # the reported distance matches the metric (full mass projected onto the
        # reduced support).
        assert np.isclose(d, kantorovich_distance(scen, reduced, p=2), rtol=1e-6, atol=1e-6)
        distances.append(d)

    # (b) monotone non-increasing trade-off, and identity (distance 0) at full size.
    curve = list(zip(ks, distances, strict=True))
    assert all(distances[i] >= distances[i + 1] - 1e-9 for i in range(len(distances) - 1)), (
        f"reduction distance not monotone in k on real data: {curve}"
    )
    _, d_full = reduce_scenarios(scen, n_reduced=scen.n_scenarios, method="forward")
    assert d_full == 0.0
