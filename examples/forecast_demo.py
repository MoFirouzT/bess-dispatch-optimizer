#!/usr/bin/env python3
"""Probabilistic forecaster demo (R2.1) — calibrated day-ahead price intervals.

Fits the LightGBM + conformal forecaster, measures its **empirical coverage** under
the walk-forward (leakage-safe) discipline, and draws a fan chart of one held-out
block: the calibrated interval as a shaded band, the point forecast, and the price
that actually cleared. The honest test of a conformal interval is that the realized
price lands inside the band about as often as the nominal level claims.

The **committed** figure is built from real ENTSO-E NL prices. To reproduce it, set
a token and run:

    ENTSOE_API_TOKEN=... uv run --group forecast --group examples python examples/forecast_demo.py

Without a token it falls back to a deterministic **synthetic** NL-like series that
traces the same shape. Numbers are illustrative, not a gate (the coverage gate in
``tests/`` owns correctness); no real price data is committed, only the chart.

Needs both optional groups: ``forecast`` (LightGBM/MAPIE) and ``examples``
(matplotlib).
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from bess.forecaster import PriceForecaster, walk_forward_coverage

CONFIDENCE = 0.9
N_DAYS = 55  # fetch/synthesize window
BLOCK_DAYS = 3  # held-out block drawn in the fan chart
N_ESTIMATORS = 300  # committed-quality LightGBM; the smoke test shrinks this
FIG = Path(__file__).resolve().parent.parent / "docs" / "figures" / "example-forecast-intervals.svg"


def _load_prices() -> tuple[pd.Series, str]:
    """Real NL hourly day-ahead if a token is set, else the synthetic fallback."""
    if os.environ.get("ENTSOE_API_TOKEN"):
        from bess.data.entsoe import fetch_day_ahead

        end = pd.Timestamp("2024-05-31 23:00", tz="UTC")
        start = end.normalize() - pd.Timedelta(days=N_DAYS - 1)
        return fetch_day_ahead("NL", start, end), "real NL, 2024"

    from bess.data.fixtures import synthetic_day_ahead

    return synthetic_day_ahead(days=N_DAYS), "synthetic"


def main() -> None:
    prices, tag = _load_prices()
    print(f"Forecaster demo — {tag} series, {len(prices)} hourly points\n")

    # Pooled walk-forward coverage: the headline number (the gate owns correctness).
    coverage, width = walk_forward_coverage(
        prices, confidence_level=CONFIDENCE, method="cqr", n_folds=3, test_days=5,
        n_estimators=N_ESTIMATORS,
    )  # fmt: skip
    print(f"walk-forward coverage {coverage * 100:.1f}% (nominal {CONFIDENCE * 100:.0f}%),")
    print(f"mean interval width {width:.1f} EUR/MWh\n")

    # Fan chart: fit on everything before the last block, predict the block, overlay
    # the realized price. Features for the block come from prior days, so no leakage.
    days = sorted(prices.index.normalize().unique())
    block_days = days[-BLOCK_DAYS:]
    block_start, block_end = block_days[0], block_days[-1]
    norm = prices.index.normalize()
    train = prices[norm < block_start]
    hist_and_block = prices[norm <= block_end]

    forecaster = PriceForecaster(
        confidence_level=CONFIDENCE, method="cqr", n_estimators=N_ESTIMATORS
    )
    forecaster.fit(train)
    fc = forecaster.predict_interval(hist_and_block)

    mask = (fc.point.index.normalize() >= block_start) & (fc.point.index.normalize() <= block_end)
    targets = fc.point.index[mask]
    realized = prices.loc[targets]
    hours = list(range(len(targets)))

    from bess.viz.forecast_plots import plot_forecast_intervals

    FIG.parent.mkdir(parents=True, exist_ok=True)
    fig = plot_forecast_intervals(
        hours,
        fc.point[mask].to_numpy(),
        fc.lower[mask].to_numpy(),
        fc.upper[mask].to_numpy(),
        realized.to_numpy(),
        confidence_level=CONFIDENCE,
        coverage=coverage,
        title=f"Conformal price forecast — calibrated intervals ({tag})",
    )
    fig.savefig(FIG, format="svg", bbox_inches="tight")
    print(f"wrote {FIG.name} to docs/figures/ ({tag})")


if __name__ == "__main__":
    main()
