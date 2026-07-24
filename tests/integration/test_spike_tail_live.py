"""Integration — R2.2b extreme-value tail on real ENTSO-E NL prices.

Contract: docs/specs/R2.2b-spike-tail.md § "Acceptance gate". Token-gated (skipped
unless `ENTSOE_API_TOKEN` is set; deselected in CI via the `integration` marker);
nothing fetched is committed. Mirrors the R2.2 live test's residual-path setup
(mean day shape as the point, real-day deviations as residuals), so no forecast
group is needed.

What it proves on *real* prices:
  (a) un-capping: the GPD-tail scenario set exceeds the plain bootstrap's maximum,
      which is capped at the historical-maximum residual by construction; and
  (b) tail coverage (headline, honest): the plain bootstrap's per-hour support
      ceiling (its maximum) is capped, so realized held-out spikes above it get zero
      probability; the GPD tail extends the ceiling and covers more of them. Reported
      with provenance, not asserted-positive beyond "no worse". (Measured finding: the
      *body* 99th-percentile coverage is dominated by the crude mean-day-shape point,
      not the tail, so the ceiling, where the cap actually bites, is the honest metric.)

Network setup (this machine): a TLS-intercepting proxy means uv-Python may need the
Keychain roots — see docs/specs/R1.4b-entsoe-loader.md § "Environment note".
"""

import os
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from bess.data.entsoe import fetch_day_ahead
from bess.scenarios import TailModel, generate_scenarios

pytestmark = pytest.mark.integration

requires_token = pytest.mark.skipif(
    not os.environ.get("ENTSOE_API_TOKEN"),
    reason="ENTSOE_API_TOKEN not set — live ENTSO-E integration test skipped (never runs in CI)",
)


@requires_token
def test_tail_un_caps_and_improves_tail_coverage_on_real_prices():
    # ~4 months of real NL hourly day-ahead prices → genuine day shapes. Never committed.
    prices = fetch_day_ahead(
        "NL", pd.Timestamp("2024-02-01", tz="UTC"), pd.Timestamp("2024-06-01", tz="UTC")
    )
    values = prices.to_numpy(dtype=float)
    usable = (len(values) // 24) * 24
    days = values[:usable].reshape(-1, 24)  # (M, 24)
    index = pd.date_range("2026-01-01", periods=24, freq="h", tz="UTC")

    cut = (len(days) * 2) // 3
    train, test = days[:cut], days[cut:]  # residual history vs held-out realized days
    point = train.mean(axis=0)
    residuals = train - point
    hist_max = residuals.max()
    forecast = SimpleNamespace(point=pd.Series(point, index=index, name="price_eur_mwh"))

    tail = TailModel.fit(residuals, threshold_quantile=0.95, side="upper")

    plain = generate_scenarios(forecast, residuals, n=3000, seed=0)
    spliced = generate_scenarios(forecast, residuals, n=3000, seed=0, tail=tail)

    # (a) un-capping on real data: the plain bootstrap cannot exceed the historical
    # maximum; the GPD tail does.
    plain_max_resid = (plain.paths - point).max()
    tail_max_resid = (spliced.paths - point).max()
    assert plain_max_resid <= hist_max + 1e-9
    assert tail_max_resid > hist_max

    # (b) tail coverage at the support ceiling (where the cap bites): the per-hour
    # maximum across scenarios is the highest price the set assigns any probability.
    # Realized spikes above it are un-representable by that set.
    ceil_plain = plain.paths.max(axis=0)
    ceil_tail = spliced.paths.max(axis=0)
    assert np.all(ceil_tail >= ceil_plain - 1e-9)  # the tail extends the upper support
    above_plain = float(np.mean(test > ceil_plain))  # realized spikes the plain set can't reach
    above_tail = float(np.mean(test > ceil_tail))

    print(
        f"\nR2.2b live (NL 2024, held-out {len(test)} days):"
        f"\n  plain bootstrap : realized above support ceiling={above_plain:.4f}"
        f"  max_resid={plain_max_resid:.1f}"
        f"\n  + GPD tail      : realized above support ceiling={above_tail:.4f}"
        f"  max_resid={tail_max_resid:.1f}"
        f"  (xi={tail.xi:.2f}, beta={tail.beta:.1f}, u={tail.threshold:.1f})"
    )

    # The tail extends the upper support, so fewer realized spikes fall outside it.
    assert above_tail <= above_plain + 1e-9
