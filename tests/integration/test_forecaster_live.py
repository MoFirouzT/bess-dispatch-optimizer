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
from bess.data.ingestion_guard import FeedStatus, guarded_fetch  # noqa: E402
from bess.forecaster import walk_forward_coverage  # noqa: E402
from bess.forecaster.forecast import PriceForecaster  # noqa: E402

pytestmark = pytest.mark.integration

requires_token = pytest.mark.skipif(
    not os.environ.get("ENTSOE_API_TOKEN"),
    reason="ENTSOE_API_TOKEN not set — live ENTSO-E integration test skipped (never runs in CI)",
)

_FAST = dict(n_estimators=60, random_state=0)

_TRAIN_WINDOW = (pd.Timestamp("2024-02-01", tz="UTC"), pd.Timestamp("2024-06-01", tz="UTC"))
#: A season the training window does not reach: NL late autumn / winter. Deliberately
#: disjoint and *later*, so no lag can bridge the two windows.
_WINTER_WINDOW = (pd.Timestamp("2024-11-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC"))

#: The R2.1 coverage gate band (`test_coverage_gate_on_real_prices`), reused below as
#: the thing out-of-season coverage is shown *not* to satisfy.
_GATE_BAND = (0.85, 0.95)


def _guarded_prices(window):
    """Fetch a window through the R1.4c guard, hard-stopping on a degraded feed."""
    result = guarded_fetch(lambda: fetch_day_ahead("NL", *window), last_known_good=None)
    assert result.status is FeedStatus.HEALTHY, f"real NL feed classified {result.status.value}"
    assert result.degraded is False
    return result.prices


@requires_token
@pytest.mark.parametrize("method", ["cqr", "split"])
def test_coverage_gate_on_real_prices(method):
    # ~4 months of real NL hourly day-ahead prices — enough history for the CQR
    # calibration split plus a 3-fold walk-forward. Fetched live, never committed.
    #
    # The fetch goes through the R1.4c guard (ADR-0013: the consumer wires the guard,
    # the guard never reaches up), so the forecaster cannot be calibrated on a feed
    # that silently lied. `last_known_good=None` is deliberate: this test asserts
    # coverage *on real prices*, so a degraded feed must hard-stop with
    # `IngestionGuardError` rather than quietly substitute a fallback series and let
    # the gate report real-data coverage it never measured.
    result = guarded_fetch(
        lambda: fetch_day_ahead(
            "NL", pd.Timestamp("2024-02-01", tz="UTC"), pd.Timestamp("2024-06-01", tz="UTC")
        ),
        last_known_good=None,
    )
    assert result.status is FeedStatus.HEALTHY, f"real NL feed classified {result.status.value}"
    assert result.degraded is False

    coverage, width = walk_forward_coverage(
        result.prices, confidence_level=0.9, method=method, n_folds=3, test_days=5, **_FAST
    )

    # The conformal marginal-coverage guarantee holds on real prices too: empirical
    # coverage lands in the spec's 0.9 ± 0.05 band, and intervals have positive width.
    assert 0.85 <= coverage <= 0.95, (
        f"{method}: real-data coverage {coverage:.3f} outside [0.85, 0.95]"
    )
    assert width > 0.0


@requires_token
@pytest.mark.parametrize("method", ["cqr", "split"])
def test_coverage_gate_does_not_transfer_out_of_season(method):
    """The coverage gate above is an **in-season** result, and this pins that limit.

    `test_coverage_gate_on_real_prices` trains and tests inside one Feb-Jun window, so
    every fold's test block sits in the same season as its training data. That makes
    its 0.9 ± 0.05 result a claim about *near-term* intervals, not about the forecaster
    in general, and nothing else in the suite says so. Here the same fit is pointed at
    NL Nov-Dec, a season the training window never sees, and the interval
    under-covers: **0.776 (cqr) / 0.828 (split) against a nominal 0.9**, both below the
    gate band's floor.

    Two causes, and the second is the one that bites:
      * the price regime itself moves (train mean/std 62.87/35.69 EUR/MWh, Nov-Dec
        110.59/68.25), so intervals calibrated on the calmer season are too narrow; and
      * `month` is a plain numeric feature, so a tree trained on months 2-6 can only
        split inside that range. At month=12 every split resolves the same way it would
        in June, and the model has no representation of winter at all.

    This measures a **stale** fit, deliberately: no recalibration between the June
    fit and the December prediction. That is the case the number above describes, and
    it is not the only option — rolling `recalibrate` on a trailing winter window
    recovers most of the gap (measured: cqr 0.776 → 0.834 on a trailing 7 days and
    0.883 on 28; split 0.828 → 0.888 / 0.885), at the cost of roughly 60% wider
    intervals. So the finding is about a model left alone across a season boundary,
    not about the forecaster being unfixable.

    Pinned so it cannot regress silently, in the same spirit as the R2.4
    degenerate-optimum golden. **If it starts failing because coverage rose into the
    band, that is good news and not a broken test** — it means the seasonal limitation
    was fixed at the model level (cyclical calendar encoding, or a training window
    spanning the year), and the honest response is to update the README/spec claim
    rather than to loosen this assertion.
    """
    train = _guarded_prices(_TRAIN_WINDOW)
    winter = _guarded_prices(_WINTER_WINDOW)

    # The two windows really are disjoint, and winter really is a different regime;
    # without both, the under-coverage below would prove nothing.
    assert train.index[-1] < winter.index[0]
    assert winter.mean() > 1.5 * train.mean()

    forecaster = PriceForecaster(confidence_level=0.9, method=method, **_FAST).fit(train)
    forecast = forecaster.predict_interval(winter)
    realized = winter.loc[forecast.point.index]
    coverage = float(((realized >= forecast.lower) & (realized <= forecast.upper)).mean())

    assert len(realized) > 1000, "winter block too short to read a coverage rate from"
    assert coverage < _GATE_BAND[0], (
        f"{method}: out-of-season coverage {coverage:.3f} now reaches the in-season "
        f"gate band {_GATE_BAND} — the seasonal limitation this test pins may be "
        "fixed; re-check the R2.1 coverage claim instead of relaxing this bound"
    )
