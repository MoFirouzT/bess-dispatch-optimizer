"""Summary statistics for a per-window value distribution (R2.7).

Spec: ``docs/specs/study-windowing.md``; math: ``docs/formulation-evaluation.md``
§R2.5. Every value study reports a distribution over delivery windows rather than a
single number, and this is where that distribution becomes the handful of figures the
studies pages quote: median, quartiles, share above zero, and an interval on the
median.

**The block, not the window, is the resampling unit.** Windows inside one fold block
are consecutive days: they share 27 of their 28 training days and their realized
prices are serially correlated, so treating them as independent overstates the
evidence. The R2.5 gate did exactly that with a per-window sign test. Resampling whole
blocks instead is the same correction ``forecaster.evaluate.coverage_ci`` already
applies one level down, where the day rather than the hour is the unit.

The interval is a percentile bootstrap, so it is distribution-free: the per-window
value distribution is skewed, and nothing here assumes otherwise.

**Two different uncertainties live here (R2.8).** ``summarize_by_block`` answers "how
much would this median move on a different set of delivery days"; ``summarize_across_seeds``
answers "how much would it move on the same days with a different random seed". They
are independent, and a value claim needs both: R2.7 found the second worth about 4 EUR
on a median of +12.90, which no interval it reported covered.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class WindowSummary:
    """What a per-window distribution reports. EUR unless the caller says otherwise."""

    n_windows: int
    median: float
    q25: float
    q75: float
    share_positive: float  # strictly above zero: breaking even is not a win
    median_ci: tuple[float, float]  # block bootstrap; (nan, nan) below two blocks

    def __eq__(self, other: object) -> bool:
        """Exact equality, with NaN treated as equal to NaN.

        The dataclass default makes ``(nan, nan) != (nan, nan)``, which would make a
        determinism test on a single-block summary fail for a reason that has nothing
        to do with determinism.
        """
        if not isinstance(other, WindowSummary):
            return NotImplemented
        return (
            self.n_windows == other.n_windows
            and _same(self.median, other.median)
            and _same(self.q25, other.q25)
            and _same(self.q75, other.q75)
            and _same(self.share_positive, other.share_positive)
            and _same(self.median_ci[0], other.median_ci[0])
            and _same(self.median_ci[1], other.median_ci[1])
        )

    __hash__ = None  # type: ignore[assignment]


def _same(a: float, b: float) -> bool:
    return bool((np.isnan(a) and np.isnan(b)) or a == b)


def summarize_by_block(
    values: Sequence[float] | np.ndarray,
    block_ids: Sequence[int] | np.ndarray,
    *,
    level: float = 0.95,
    n_boot: int = 2000,
    seed: int = 0,
) -> WindowSummary:
    """Summarize per-window ``values``, with a block-bootstrap interval on the median.

    ``block_ids`` labels which fold block each value came from; values sharing a label
    are resampled together, which is the whole point. Resampling draws ``B`` blocks
    with replacement from the ``B`` observed blocks, pools their values, and takes the
    median, ``n_boot`` times; the interval is the central ``level`` of those medians.

    With fewer than two distinct blocks the interval is ``(nan, nan)``: there is no
    between-block variation to resample, and a zero-width interval would read as
    certainty rather than as absence of evidence.
    """
    v = np.asarray(values, dtype=float)
    b = np.asarray(block_ids)
    if v.ndim != 1:
        raise ValueError(f"values must be 1-D; got shape {v.shape}")
    if v.shape != b.shape:
        raise ValueError(f"values and block_ids must align; got {v.shape} and {b.shape}")
    if v.size == 0:
        raise ValueError("cannot summarize an empty window set")
    if not 0.0 < level < 1.0:
        raise ValueError(f"level must be in (0, 1); got {level}")

    q25, med, q75 = (float(x) for x in np.percentile(v, [25, 50, 75]))

    groups = [v[b == label] for label in pd.unique(b)]
    if len(groups) < 2:
        ci = (float("nan"), float("nan"))
    else:
        rng = np.random.default_rng(seed)
        n_blocks = len(groups)
        medians = np.empty(n_boot, dtype=float)
        for i in range(n_boot):
            picked = rng.integers(0, n_blocks, size=n_blocks)
            medians[i] = np.median(np.concatenate([groups[j] for j in picked]))
        tail = (1.0 - level) / 2.0
        lo, hi = np.percentile(medians, [100.0 * tail, 100.0 * (1.0 - tail)])
        ci = (float(lo), float(hi))

    return WindowSummary(
        n_windows=int(v.size),
        median=med,
        q25=q25,
        q75=q75,
        share_positive=float(np.mean(v > 0.0)),
        median_ci=ci,
    )


def summarize_by_year(
    values: Sequence[float] | np.ndarray,
    window_starts: Sequence[pd.Timestamp],
    *,
    level: float = 0.95,
    n_boot: int = 2000,
    seed: int = 0,
) -> dict[int, WindowSummary]:
    """Split a per-window distribution by the delivery day's calendar year.

    The regime breakdown R2.7 exists to report: NL price levels differ roughly 3x
    across 2022 to 2025, so a pooled median can hide a finding that holds in one regime
    and reverses in another.

    Within a year the blocks are re-labelled by contiguous runs of days, since a fold
    block never straddles a year boundary in the R2.7 layout but a caller passing a
    contiguous sweep has no blocks at all. Years holding a single run report no
    interval, on the same rule as ``summarize_by_block``.
    """
    v = np.asarray(values, dtype=float)
    starts = pd.DatetimeIndex(list(window_starts))
    if v.shape[0] != len(starts):
        raise ValueError(f"values and window_starts must align; got {v.shape[0]} and {len(starts)}")

    out: dict[int, WindowSummary] = {}
    for year in sorted(set(starts.year)):
        mask = starts.year == year
        days = starts[mask]
        # A new block starts wherever the day sequence jumps: contiguous runs are the
        # dependence unit, which is what the R2.7 fold blocks are. Compare Timedeltas,
        # not the raw `asi8` integers: a DatetimeIndex may carry microsecond or
        # nanosecond resolution, so an integer comparison against a fixed constant
        # silently marks every step a gap on the unit it was not written for.
        gaps = (days[1:] - days[:-1]) != pd.Timedelta(days=1)
        blocks = np.concatenate([[0], np.cumsum(np.asarray(gaps))])
        out[int(year)] = summarize_by_block(v[mask], blocks, level=level, n_boot=n_boot, seed=seed)
    return out


@dataclass(frozen=True)
class SeedSpread:
    """How far a study's headline median travels when only the seed changes.

    Not a confidence interval. Every seed is an equally valid run of the same protocol
    on the same days, so this is the reproducibility of the number itself: the width a
    reader should not read meaning into.
    """

    n_seeds: int
    mean_median: float
    sd_median: float  # population sd across seeds, not a standard error
    min_median: float
    max_median: float

    @property
    def spread(self) -> float:
        """Max minus min: the plainest statement of how far the headline moved."""
        return self.max_median - self.min_median


def summarize_across_seeds(medians_by_seed: Mapping[int, float]) -> SeedSpread:
    """Spread of a per-window median across repeated runs that differ only in seed.

    Takes the median each seed produced, keyed by that seed. Deliberately takes
    medians rather than raw per-window values: the quantity whose stability matters is
    the one the studies pages quote, and pooling windows across seeds would instead
    describe a distribution nobody reports.

    Raises on fewer than two seeds, since a spread over one run is not a spread.
    """
    if len(medians_by_seed) < 2:
        raise ValueError(f"need at least 2 seeds to measure a spread; got {len(medians_by_seed)}")
    v = np.asarray([float(medians_by_seed[k]) for k in sorted(medians_by_seed)], dtype=float)
    if not np.isfinite(v).all():
        raise ValueError("every seed must contribute a finite median")
    return SeedSpread(
        n_seeds=int(v.size),
        mean_median=float(v.mean()),
        sd_median=float(v.std(ddof=0)),
        min_median=float(v.min()),
        max_median=float(v.max()),
    )
