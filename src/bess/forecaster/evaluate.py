"""Walk-forward coverage evaluation for the price forecaster (R2.1).

Spec: ``docs/specs/R2.1-forecaster.md`` § "Gates". The honest test of a conformal
forecaster is **empirical coverage on data it did not calibrate on, under the R1.4
walk-forward discipline**: for each fold, fit on all strictly-earlier data, predict
a later block, and check how often the realized price falls inside the interval.
Aggregated coverage should land in ``confidence_level ± tolerance`` (the coverage
gate). No look-ahead: a fold never trains on data at or after its test block.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bess.forecaster.forecast import PriceForecaster


def walk_forward_coverage(
    prices: pd.Series,
    *,
    confidence_level: float = 0.9,
    method: str = "cqr",
    n_folds: int = 3,
    test_days: int = 5,
    **forecaster_params: object,
) -> tuple[float, float]:
    """Return ``(empirical_coverage, mean_interval_width)`` over a walk-forward.

    The last ``n_folds * test_days`` days are split into ``n_folds`` consecutive test
    blocks. For each block, a fresh forecaster is fit on all days strictly before the
    block and used to predict it (features for the block come from prior days, so no
    leakage). Coverage is pooled across all test points.
    """
    days = np.array(sorted(prices.index.normalize().unique()))
    total_test = n_folds * test_days
    if len(days) <= total_test + 1:
        raise ValueError("series too short for the requested walk-forward")

    covered = 0
    count = 0
    widths: list[float] = []
    for fold in range(n_folds):
        start = len(days) - total_test + fold * test_days
        test_days_block = days[start : start + test_days]
        block_start, block_end = test_days_block[0], test_days_block[-1]

        norm = prices.index.normalize()
        train = prices[norm < block_start]
        hist_and_block = prices[norm <= block_end]

        forecaster = PriceForecaster(
            confidence_level=confidence_level, method=method, **forecaster_params
        )
        forecaster.fit(train)
        forecast = forecaster.predict_interval(hist_and_block)

        f_norm = forecast.point.index.normalize()
        block_mask = (f_norm >= block_start) & (f_norm <= block_end)
        targets = forecast.point.index[block_mask]
        y_true = prices.loc[targets].to_numpy()
        lo = forecast.lower[block_mask].to_numpy()
        hi = forecast.upper[block_mask].to_numpy()

        covered += int(((y_true >= lo) & (y_true <= hi)).sum())
        count += len(targets)
        widths.append(float((hi - lo).mean()))

    return covered / count, float(np.mean(widths))
