"""Sharpness search: the narrowest conformal interval that stays calibrated (R2.1f).

Spec: ``docs/specs/interval-sharpness.md``; math: ``formulation-uncertainty.md`` §R2.1.

**Conformal calibration turns hyperparameter tuning into a search over width alone.**
Whatever the three quantile learners do, the conformal step moves the bounds until
marginal coverage lands near ``1 - α``, so a worse base model does not produce an
uncovered interval, it produces a wider one. Width is therefore the objective, and
coverage is a constraint that must be checked rather than a thing to optimize.

The selection rule is

    minimize   mean interval width
    subject to pooled coverage in the gate band
               per-hour coverage no worse deviated than the incumbent's

with ties broken by median width, then by the cheaper model, then by a canonical
ordering of the parameters themselves. Every tie-break is a property of the candidate,
never of where it sat in the grid, so permuting the grid cannot change the answer.

**The second constraint is the one doing real work.** Mean width is minimized by an
interval that is tight overnight and too tight at the evening peak: marginally
calibrated, conditionally wrong, and worthless to a dispatch layer that trades the
peak. Marginal coverage cannot see that failure, which is why it is a separate test
(``docs/decisions/cqr-over-split-conformal.md``).

**Candidates are selected on days no reporting gate scores.** ``tuning_folds`` places
its blocks in the *gaps* between the reporting blocks, so the width this module
minimizes is never the width the R2.1d gate later reports. Choosing and reporting on
the same blocks would make the winner's margin partly a fit to them.

The spec first put the tuning blocks in 2021, which the reporting layout uses only for
training. Implementation killed that: measured 2026-08-31 on NL at an identical
12-fold, 180-training-day placement, pooled coverage runs **0.791 in 2021, 0.847 in
2022, 0.887 in 2023, 0.897 in 2024**, against monthly NL means climbing 77 to 238
EUR/MWh across 2021 H2. Conformal coverage assumes exchangeability, a hard upward trend
in the level breaks it, and 2021 is the worst-calibrated stretch in the span: the
*incumbent* misses the band there, so no candidate is feasible and the search cannot
run. Selecting a model on the one regime where the method is out of calibration would
also have optimized width against a coverage failure. Placing the blocks in the gaps
keeps the disjointness that made 2021 attractive, and adds a regime and a training
window that match what the gate reports on.

Imports LightGBM and MAPIE transitively through ``evaluate.walk_forward_coverage``,
which does it lazily, so this module is importable without the ``forecast`` group;
calling ``search_sharpest`` is not.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import product
from typing import Any

import pandas as pd

from bess.forecaster.evaluate import (
    CoverageResult,
    Fold,
    _price_days,
    rolling_origin_folds,
    walk_forward_coverage,
)

_logger = logging.getLogger(__name__)

#: The shipped model, as a candidate. Values are ``PriceForecaster``'s own default
#: ``n_estimators`` and ``calib_fraction`` plus LightGBM's defaults for the three
#: knobs the forecaster passes no value for. A golden test reads both signatures and
#: fails if either drifts, because a search that reports a width reduction against a
#: model nobody runs has measured nothing.
INCUMBENT: dict[str, Any] = {
    "n_estimators": 200,
    "learning_rate": 0.1,
    "num_leaves": 31,
    "min_child_samples": 20,
    "calib_fraction": 0.3,
}

#: The frozen grid (spec § Parameters). Enumerated in full rather than sampled: 324
#: configurations is under half an hour at the measured cost, and exhausting the grid
#: keeps a search seed out of the result, which is one less width to report.
GRID_AXES: dict[str, tuple[Any, ...]] = {
    "n_estimators": (100, 200, 400, 800),
    "learning_rate": (0.03, 0.05, 0.1),
    "num_leaves": (15, 31, 63),
    "min_child_samples": (20, 50, 100),
    # A conformal knob, not a learner knob, and in the grid because it moves width
    # directly: it sets how many points the conformal quantile is estimated from, and
    # a short calibration block buys a noisier and typically wider correction.
    "calib_fraction": (0.2, 0.3, 0.4),
}

DEFAULT_GRID: tuple[dict[str, Any], ...] = tuple(
    dict(zip(GRID_AXES, values, strict=True)) for values in product(*GRID_AXES.values())
)

#: R2.1d's fold placement, unchanged. Its test blocks run 2022-01-01 to 2025-09-30 on
#: the 2021-2025 span, so all of 2021 is training-only.
REPORTING_LAYOUT: dict[str, Any] = dict(n_folds=52, test_days=5, train_days=365, spacing="even")

#: How many blocks the search selects on, and how long each is. Same length and same
#: 365-day training window as a reporting block, so a candidate is scored under the
#: regime it will be gated under; only the placement differs.
TUNING_N_FOLDS = 12
TUNING_TEST_DAYS = 5


def tuning_folds(
    days: pd.DatetimeIndex,
    *,
    n_folds: int = TUNING_N_FOLDS,
    test_days: int = TUNING_TEST_DAYS,
    reporting_layout: Mapping[str, Any] | None = None,
) -> list[Fold]:
    """Blocks placed in the gaps between the reporting blocks, evenly spread.

    The reporting layout leaves roughly 22 clear days between consecutive test blocks,
    so a tuning block sits in the middle of a gap without touching either neighbour.
    That buys disjointness without giving up the regime: candidates are scored on the
    same years, with the same 365-day training window, as the gate that later reports
    them.

    Raises rather than returning a short list if any placement collides, because a
    silently dropped fold would mean selecting on fewer days than the caller asked for.
    """
    layout = dict(REPORTING_LAYOUT if reporting_layout is None else reporting_layout)
    reporting = rolling_origin_folds(days, **layout)
    train_days = int(layout["train_days"])
    pos = {day: i for i, day in enumerate(days)}
    scored = {
        day for fold in reporting for day in days[pos[fold.test_start] : pos[fold.test_end] + 1]
    }

    gaps = [
        (pos[a.test_end] + 1, pos[b.test_start])  # [clear_start, clear_end)
        for a, b in zip(reporting, reporting[1:], strict=False)
    ]
    usable = [(lo, hi) for lo, hi in gaps if hi - lo >= test_days and lo >= train_days]
    if len(usable) < n_folds:
        raise ValueError(
            f"only {len(usable)} gaps between reporting blocks can host a "
            f"{test_days}-day block after a {train_days}-day training window, "
            f"but {n_folds} were requested"
        )

    # Evenly spread over the usable gaps, then centred inside the chosen gap.
    step = (len(usable) - 1) / (n_folds - 1) if n_folds > 1 else 0
    folds = []
    for i in range(n_folds):
        lo, hi = usable[round(i * step)]
        start = lo + (hi - lo - test_days) // 2
        block = days[start : start + test_days]
        if scored.intersection(block):
            raise ValueError(  # pragma: no cover - the gap arithmetic prevents it
                f"tuning block at {block[0].date()} overlaps a reporting block"
            )
        folds.append(
            Fold(
                train_start=days[start - train_days],
                train_end=days[start],
                test_start=days[start],
                test_end=days[start + test_days - 1],
            )
        )
    return folds


#: The R2.1 coverage tolerance band, the same one the live gate tests by interval
#: overlap. Here it is applied to the point estimate: this is a *filter over
#: candidates*, not the gate, and the gate still decides the shipped claim.
DEFAULT_COVERAGE_BAND = (0.85, 0.95)


@dataclass(frozen=True)
class SharpnessCandidate:
    """One configuration, scored on the tuning folds, with why it was kept or dropped."""

    params: Mapping[str, Any]
    coverage: float
    mean_width: float
    median_width: float
    max_hour_deviation: float
    feasible: bool
    #: Empty when feasible; otherwise which constraint rejected it and by how much.
    reason: str = ""

    @classmethod
    def from_result(
        cls,
        params: Mapping[str, Any],
        result: CoverageResult,
        *,
        feasible: bool = True,
        reason: str = "",
    ) -> SharpnessCandidate:
        return cls(
            params=dict(params),
            coverage=result.coverage,
            mean_width=result.mean_width,
            median_width=result.median_width,
            max_hour_deviation=result.max_hour_deviation,
            feasible=feasible,
            reason=reason,
        )


@dataclass(frozen=True)
class SharpnessSearch:
    """The search outcome: what won, what it beat, and what every candidate scored."""

    incumbent: SharpnessCandidate
    selected: SharpnessCandidate
    #: Feasible candidates only, sharpest first. Includes the incumbent.
    ranked: tuple[SharpnessCandidate, ...]
    #: Every grid candidate in grid order, infeasible ones included, so a rejected
    #: configuration can be read back with its reason instead of vanishing.
    all_candidates: tuple[SharpnessCandidate, ...]

    @property
    def width_reduction(self) -> float:
        """Mean width given up by the incumbent, in price units. Zero on a null result."""
        return self.incumbent.mean_width - self.selected.mean_width

    @property
    def is_null(self) -> bool:
        """True when nothing beat the shipped model, so the shipped model was returned."""
        return self.selected is self.incumbent


def _judge(
    params: Mapping[str, Any],
    result: CoverageResult,
    *,
    coverage_band: tuple[float, float],
    incumbent_deviation: float,
) -> SharpnessCandidate:
    """Apply the two constraints to one scored configuration."""
    lo, hi = coverage_band
    if not lo <= result.coverage <= hi:
        return SharpnessCandidate.from_result(
            params,
            result,
            feasible=False,
            reason=f"coverage {result.coverage:.3f} outside [{lo}, {hi}]",
        )
    if result.max_hour_deviation > incumbent_deviation:
        return SharpnessCandidate.from_result(
            params,
            result,
            feasible=False,
            reason=(
                f"per-hour coverage deviates {result.max_hour_deviation:.3f} against the "
                f"incumbent's {incumbent_deviation:.3f}"
            ),
        )
    return SharpnessCandidate.from_result(params, result)


def rank_candidates(
    scored: Iterable[tuple[Mapping[str, Any], CoverageResult]],
    *,
    incumbent: SharpnessCandidate,
    coverage_band: tuple[float, float] = DEFAULT_COVERAGE_BAND,
) -> SharpnessSearch:
    """Apply the selection rule to already-scored candidates.

    Split out from :func:`search_sharpest` so the rule can be tested against recorded
    ``CoverageResult`` values: the expected answer is then hand-checkable, which a
    LightGBM fit never is.

    The incumbent is always in the ranking, so the search cannot return something
    wider than what ships. It is judged against its **own** hourly deviation, which
    it meets by definition, and so is excluded only if it falls outside the band.
    """
    inc = _judge(
        incumbent.params,
        _as_result(incumbent),
        coverage_band=coverage_band,
        incumbent_deviation=incumbent.max_hour_deviation,
    )
    candidates = [
        _judge(
            params,
            result,
            coverage_band=coverage_band,
            incumbent_deviation=incumbent.max_hour_deviation,
        )
        for params, result in scored
    ]

    pool = [c for c in candidates if c.feasible]
    if inc.feasible:
        pool.append(inc)
    if not pool:
        # Degenerate: even the shipped model missed the band on these folds. Nothing is
        # selectable, and silently returning an infeasible winner would hide that.
        raise ValueError(
            "no candidate met the coverage band, including the incumbent "
            f"({inc.reason}); the tuning folds, not the grid, are the thing to look at"
        )

    pool.sort(key=_order)
    ranked = tuple(pool)
    selected = ranked[0]
    # A tie is not an improvement, so hand an exact tie back to the incumbent, by
    # identity: `is_null` asks whether the returned object *is* the incumbent, and two
    # distinct configurations can score identically.
    if inc.feasible and selected.mean_width >= inc.mean_width:
        selected = inc
    return SharpnessSearch(
        incumbent=inc,
        selected=selected,
        ranked=ranked,
        all_candidates=tuple(candidates),
    )


def _order(candidate: SharpnessCandidate) -> tuple[Any, ...]:
    """Total, order-independent sort key: sharpest, then cheapest, then canonical.

    Every component is a property of the candidate. An earlier version used the
    candidate's index in the grid as the final tie-break, which a property test caught:
    two configurations can score identically to the last bit, and index-based breaking
    made the winner depend on the order the grid happened to be written in, so the
    recorded result would not survive a re-ordered grid.

    Among exact ties the **cheaper** model wins (fewer trees, then fewer leaves).
    Equal width for less capacity is the better buy, and it is a real preference rather
    than a coin toss. The trailing parameter tuple only makes the key total.
    """
    params = candidate.params
    return (
        candidate.mean_width,
        candidate.median_width,
        params.get("n_estimators", 0),
        params.get("num_leaves", 0),
        tuple(sorted((k, str(v)) for k, v in params.items())),
    )


def _as_result(candidate: SharpnessCandidate) -> CoverageResult:
    """Re-wrap a scored candidate so it can go back through :func:`_judge`."""
    return CoverageResult(
        coverage=candidate.coverage,
        ci_low=float("nan"),
        ci_high=float("nan"),
        mean_width=candidate.mean_width,
        median_width=candidate.median_width,
        n_test_days=0,
        per_fold=(),
        by_hour=(),
        max_hour_deviation=candidate.max_hour_deviation,
    )


def score_config(
    prices: pd.Series,
    params: Mapping[str, Any],
    *,
    folds: Sequence[Fold],
    fundamentals: pd.DataFrame | None = None,
    confidence_level: float = 0.9,
    method: str = "cqr",
    random_state: int = 0,
) -> CoverageResult:
    """Walk-forward coverage, width and per-hour calibration for one configuration.

    ``calib_fraction`` is a ``PriceForecaster`` argument and the rest are LightGBM
    parameters, but ``walk_forward_coverage`` forwards both through the same
    ``**forecaster_params``, so no split is needed here.
    """
    result = walk_forward_coverage(
        prices,
        confidence_level=confidence_level,
        method=method,
        folds=folds,
        fundamentals=fundamentals,
        return_detail=True,
        random_state=random_state,
        **dict(params),
    )
    assert isinstance(result, CoverageResult)  # return_detail=True
    return result


def search_sharpest(
    prices: pd.Series,
    *,
    grid: Sequence[Mapping[str, Any]] | None = None,
    fundamentals: pd.DataFrame | None = None,
    coverage_band: tuple[float, float] = DEFAULT_COVERAGE_BAND,
    folds: Sequence[Fold] | None = None,
    confidence_level: float = 0.9,
    method: str = "cqr",
    random_state: int = 0,
    progress: bool = False,
) -> SharpnessSearch:
    """Score every configuration on the tuning folds and apply the selection rule.

    ``grid=None`` uses :data:`DEFAULT_GRID`; ``folds=None`` uses :func:`tuning_folds`
    over the price series' own days, which is the gap placement described above. Tests
    pass a small grid and their own folds to stay fast.

    Deterministic: LightGBM runs single-threaded with a fixed seed, the grid is
    enumerated rather than sampled, and every tie-break is a property of the candidate,
    so two runs with the same arguments return the same ranking.
    """
    if folds is None:
        folds = tuning_folds(_price_days(prices))
    candidates = list(DEFAULT_GRID if grid is None else grid)

    def score(params: Mapping[str, Any]) -> CoverageResult:
        return score_config(
            prices,
            params,
            folds=folds,
            fundamentals=fundamentals,
            confidence_level=confidence_level,
            method=method,
            random_state=random_state,
        )

    incumbent = SharpnessCandidate.from_result(INCUMBENT, score(INCUMBENT))

    scored: list[tuple[Mapping[str, Any], CoverageResult]] = []
    for i, params in enumerate(candidates, start=1):
        result = score(params)
        scored.append((params, result))
        if progress:
            _logger.info(
                "sharpness %d/%d %s -> width %.2f coverage %.3f",
                i,
                len(candidates),
                params,
                result.mean_width,
                result.coverage,
            )
    return rank_candidates(scored, incumbent=incumbent, coverage_band=coverage_band)
