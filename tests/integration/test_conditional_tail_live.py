"""Integration — R2.2c residual-load-conditional tail on real ENTSO-E NL.

Contract: docs/specs/R2.2c-conditional-tail.md § "Acceptance gate". Token-gated
(skipped unless `ENTSOE_API_TOKEN` is set; deselected in CI); nothing fetched is
committed. Uses the R2.1c fundamentals loader for the residual-load covariate and
the R2.2-live residual construction (mean day shape as the point).

What it proves on *real* prices:
  (a) residual load genuinely predicts spike magnitude: the fitted log-scale slope
      γ > 0 on real NL (spikes are heavier on tight-margin hours); and
  (b) the conditioning reaches generation: a target hour with high residual load
      draws larger spikes than one with low residual load. Reported with
      provenance; γ ≈ 0 on another asset/window would be a reported null.

Network setup (this machine): a TLS-intercepting proxy means uv-Python may need the
Keychain roots — see docs/specs/R1.4b-entsoe-loader.md § "Environment note".
"""

import os
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from bess.data.entsoe import fetch_day_ahead, fetch_fundamentals
from bess.scenarios import ConditionalTailModel, generate_scenarios

pytestmark = pytest.mark.integration

requires_token = pytest.mark.skipif(
    not os.environ.get("ENTSOE_API_TOKEN"),
    reason="ENTSOE_API_TOKEN not set — live ENTSO-E integration test skipped (never runs in CI)",
)


@requires_token
def test_residual_load_predicts_spike_magnitude_on_real_prices():
    start = pd.Timestamp("2024-02-01", tz="UTC")
    end = pd.Timestamp("2024-06-01", tz="UTC")
    prices = fetch_day_ahead("NL", start, end)
    fund = fetch_fundamentals("NL", start, end).reindex(prices.index)
    residual_load = (fund["load_da"] - fund["wind_da"] - fund["solar_da"]).to_numpy()

    values = prices.to_numpy(dtype=float)
    usable = (len(values) // 24) * 24
    days = values[:usable].reshape(-1, 24)
    rl = residual_load[:usable].reshape(-1, 24)
    point = days.mean(axis=0)
    residuals = days - point  # (M, 24) price residuals

    model = ConditionalTailModel.fit(residuals, rl, threshold_quantile=0.95, side="upper")
    x = rl.ravel()
    lo_rl, hi_rl = float(np.percentile(x, 10)), float(np.percentile(x, 90))
    beta_lo = model.beta_at(np.array([lo_rl]))[0]
    beta_hi = model.beta_at(np.array([hi_rl]))[0]

    pct = 100 * (beta_hi / beta_lo - 1)
    print(
        f"\nR2.2c live (NL 2024): gamma={model.gamma:.3f}  xi={model.xi:.2f}"
        f"  beta0={model.beta0:.1f}"
        f"\n  tail scale beta: slack hour (10th pct residual load)={beta_lo:.1f}"
        f"  ->  tight hour (90th pct)={beta_hi:.1f}  (+{pct:.0f}%)"
    )

    # (a) residual load genuinely predicts spike magnitude on this asset/window.
    assert model.gamma > 0.0, "no residual-load -> spike-magnitude signal (gamma clamped to 0)"

    # (b) the conditioning reaches generation: a two-hour target, slack vs tight, forced
    # to exceed every draw; the tight hour draws larger spikes.
    fc2 = SimpleNamespace(
        point=pd.Series(
            [50.0, 50.0], index=pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
        )
    )
    resid2 = np.abs(np.random.default_rng(0).normal(0, 10, size=(40, 2))) + model.threshold + 20.0
    cov2 = np.array([lo_rl, hi_rl])
    gen = generate_scenarios(fc2, resid2, n=6000, seed=0, tail=model, tail_covariate=cov2)
    spikes = gen.paths - 50.0
    assert spikes[:, 1].mean() > spikes[:, 0].mean()  # tight hour spikes larger
