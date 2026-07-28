"""Shared window machinery for the value studies.

A *window* is exactly one complete UTC day of hourly prices. Every study in this
package scores per-window and reports a distribution, so the day-splitting and
training-set construction live here once rather than in each study.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from bess.scenarios import ScenarioSet

_HOURS = 24  # a window is one UTC day of hourly prices (spec § Parameters)


@dataclass(frozen=True)
class _MeanForecast:
    """A bare mean-day forecast: satisfies ``scenarios.PointForecast`` (only ``.point``
    is read), so the tail-value harness builds scenarios without the forecast group."""

    point: pd.Series


def _complete_day_matrix(prices: pd.Series) -> tuple[list[pd.Timestamp], np.ndarray]:
    """Split an hourly series into complete UTC days: (day starts, (D, 24) matrix).

    Incomplete days (a truncated head/tail, a DST-affected local grouping fed in
    by mistake) are dropped, not padded: a window is exactly one full day.
    """
    s = prices.sort_index()
    idx = pd.DatetimeIndex(s.index)
    starts: list[pd.Timestamp] = []
    rows: list[np.ndarray] = []
    for day, chunk in s.groupby(idx.normalize()):
        if len(chunk) == _HOURS:
            starts.append(day)
            rows.append(chunk.to_numpy(dtype=float))
    return starts, np.asarray(rows)


def window_sets(
    prices: pd.Series,
    *,
    history_days: int = 28,
    n_scenarios: int = 30,
    seed: int = 0,
) -> list[tuple[pd.Timestamp, ScenarioSet, ScenarioSet]]:
    """Build each window's (start, training set, evaluation set) triple.

    For every complete UTC day with ``history_days`` complete days strictly
    before it: the training set is ``n_scenarios`` equiprobable day-paths drawn
    with replacement from those trailing days (an empirical bootstrap over
    recent day shapes; the §R1.4 information set, so nothing at or after the
    window enters), and the evaluation set is the window's own realized path
    (S = 1). Deterministic under ``seed``.
    """
    if history_days < 1:
        raise ValueError(f"history_days must be >= 1; got {history_days}")
    if n_scenarios < 1:
        raise ValueError(f"n_scenarios must be >= 1; got {n_scenarios}")
    starts, mat = _complete_day_matrix(prices)
    rng = np.random.default_rng(seed)
    out: list[tuple[pd.Timestamp, ScenarioSet, ScenarioSet]] = []
    for i in range(history_days, len(starts)):
        index = pd.date_range(starts[i], periods=_HOURS, freq="h")
        draws = rng.integers(0, history_days, size=n_scenarios)
        train = ScenarioSet(
            paths=mat[i - history_days : i][draws],
            probs=np.full(n_scenarios, 1.0 / n_scenarios),
            index=index,
        )
        evaluation = ScenarioSet(paths=mat[i][None, :], probs=np.array([1.0]), index=index)
        out.append((starts[i], train, evaluation))
    return out
