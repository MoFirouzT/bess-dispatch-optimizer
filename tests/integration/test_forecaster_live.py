"""Integration — R2.1 forecaster coverage on real ENTSO-E prices, walk-forward.

Contract: docs/specs/R2.1-forecaster.md § "Gates" (coverage gate, re-validated on
real ENTSO-E) and § "Acceptance": empirical coverage of the conformal interval at
nominal 0.9 lands in the stated 0.9 ± 0.05 band on data the model did not
calibrate on, under the R1.4 walk-forward discipline — on *real* prices, not just
the synthetic series.

Doubly gated: needs both the `forecast` dependency group (LightGBM + MAPIE) and a
token. `importorskip` skips cleanly when the group is absent (so the main CI job,
synced without the group, never errors at collection); the `integration` marker +
`ENTSOE_API_TOKEN` skip/deselect keep it off every CI job. Nothing fetched here is
committed. Run locally with: `uv run --group forecast pytest
tests/integration/test_forecaster_live.py` (token loaded).

Network setup (this machine): a TLS-intercepting proxy means uv-Python may need the
Keychain roots — see docs/specs/R1.4b-entsoe-loader.md § "Environment note".
"""

import os

import pytest

pytest.importorskip("lightgbm")
pytest.importorskip("mapie")

import pandas as pd  # noqa: E402

from bess.data.entsoe import fetch_day_ahead  # noqa: E402
from bess.forecaster import walk_forward_coverage  # noqa: E402

pytestmark = pytest.mark.integration

requires_token = pytest.mark.skipif(
    not os.environ.get("ENTSOE_API_TOKEN"),
    reason="ENTSOE_API_TOKEN not set — live ENTSO-E integration test skipped (never runs in CI)",
)

_FAST = dict(n_estimators=60, random_state=0)


@requires_token
@pytest.mark.parametrize("method", ["cqr", "split"])
def test_coverage_gate_on_real_prices(method):
    # ~4 months of real NL hourly day-ahead prices — enough history for the CQR
    # calibration split plus a 3-fold walk-forward. Fetched live, never committed.
    prices = fetch_day_ahead(
        "NL", pd.Timestamp("2024-02-01", tz="UTC"), pd.Timestamp("2024-06-01", tz="UTC")
    )

    coverage, width = walk_forward_coverage(
        prices, confidence_level=0.9, method=method, n_folds=3, test_days=5, **_FAST
    )

    # The conformal marginal-coverage guarantee holds on real prices too: empirical
    # coverage lands in the spec's 0.9 ± 0.05 band, and intervals have positive width.
    assert 0.85 <= coverage <= 0.95, (
        f"{method}: real-data coverage {coverage:.3f} outside [0.85, 0.95]"
    )
    assert width > 0.0
