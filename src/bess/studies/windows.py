"""Shared window machinery for the value studies.

A *window* is exactly one complete UTC day of hourly prices. Every study in this
package scores per-window and reports a distribution, so the day-splitting and
training-set construction live here once rather than in each study.

**A window's result is a property of the window (R2.7).** Every random draw a window
needs is derived from ``(seed, that window's date)``, never from its position in the
series it arrived in. That is what makes ``only_days`` a *filter*: scoring a chosen
set of delivery days returns exactly what scoring every day and discarding the rest
returns, bitwise. Before R2.7 the draws came from one generator walked in order, so
the same calendar day scored inside a 4-month series and inside a 4.7-year series was
two different experiments; see ``docs/specs/study-windowing.md``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from bess.forecaster.evaluate import Fold
from bess.scenarios import ScenarioSet

_HOURS = 24  # a window is one UTC day of hourly prices (spec § Parameters)

#: Reference date for turning a window start into the stable integer that seeds it.
#: Arbitrary but fixed: changing it would re-roll every study's draws.
_SEED_EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


def _as_utc_days(days: Sequence[pd.Timestamp] | pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Normalize an arbitrary day-ish index to sorted, unique UTC midnight stamps."""
    idx = pd.DatetimeIndex(list(days))
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    return idx.normalize().unique().sort_values()


def window_seed(seed: int, day: pd.Timestamp) -> int:
    """A stable per-``(seed, day)`` integer, for studies that seed scenario generation.

    Studies previously passed ``seed + i`` for the window's ordinal ``i``, which ties a
    window's scenarios to how many windows preceded it. Keying on the date instead
    makes a window's scenario set reproducible from any slice containing that day.
    """
    ordinal = int((_as_utc_days([day])[0] - _SEED_EPOCH).days)
    return int(np.random.SeedSequence([int(seed), ordinal]).generate_state(1)[0])


def fold_days(folds: Sequence[Fold]) -> pd.DatetimeIndex:
    """The union of the folds' test blocks, as sorted unique UTC day starts.

    Pure set union: a day appearing in two folds contributes once, so a caller cannot
    double-weight a window in the reported distribution by passing overlapping blocks.
    """
    days = [d for f in folds for d in pd.date_range(f.test_start, f.test_end, freq="D", tz="UTC")]
    return _as_utc_days(days) if days else pd.DatetimeIndex([], tz="UTC")


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
    only_days: Sequence[pd.Timestamp] | pd.DatetimeIndex | None = None,
) -> list[tuple[pd.Timestamp, ScenarioSet, ScenarioSet]]:
    """Build each window's (start, training set, evaluation set) triple.

    For every complete UTC day with ``history_days`` complete days strictly
    before it: the training set is ``n_scenarios`` equiprobable day-paths drawn
    with replacement from those trailing days (an empirical bootstrap over
    recent day shapes; the §R1.4 information set, so nothing at or after the
    window enters), and the evaluation set is the window's own realized path
    (S = 1). Deterministic under ``seed``.

    ``only_days`` restricts the output to the given delivery days, which is how the
    R2.7 fold layout selects its 260 evaluated days. It is a **filter and nothing
    more**: each surviving window carries exactly the draws it would have carried in
    the unfiltered call, because those draws come from ``(seed, the window's date)``.
    Days that cannot be scored (outside the series, or inside the ``history_days``
    head) are dropped silently rather than padded, mirroring how incomplete days are
    handled: a window is one full day or it is not a window.
    """
    if history_days < 1:
        raise ValueError(f"history_days must be >= 1; got {history_days}")
    if n_scenarios < 1:
        raise ValueError(f"n_scenarios must be >= 1; got {n_scenarios}")
    starts, mat = _complete_day_matrix(prices)
    wanted = None if only_days is None else set(_as_utc_days(only_days))
    out: list[tuple[pd.Timestamp, ScenarioSet, ScenarioSet]] = []
    for i in range(history_days, len(starts)):
        start = starts[i]
        if wanted is not None and start not in wanted:
            continue
        index = pd.date_range(start, periods=_HOURS, freq="h")
        # Keyed on the window's date, never on ``i``: see the module docstring.
        rng = np.random.default_rng(window_seed(seed, start))
        draws = rng.integers(0, history_days, size=n_scenarios)
        train = ScenarioSet(
            paths=mat[i - history_days : i][draws],
            probs=np.full(n_scenarios, 1.0 / n_scenarios),
            index=index,
        )
        evaluation = ScenarioSet(paths=mat[i][None, :], probs=np.array([1.0]), index=index)
        out.append((start, train, evaluation))
    return out
