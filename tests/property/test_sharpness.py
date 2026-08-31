"""Property tests for the sharpness search (R2.1f).

Spec: ``docs/specs/interval-sharpness.md`` § "Property tests". These hold for any
grid, so they are driven by recorded ``CoverageResult`` values rather than by fits;
the invariants are about the selection rule, which is where a subtle break would hide.

The fold-disjointness property is the exception and uses the real fold placer: it is
the property that keeps the reported width from being the width the winner was
selected on, and it is a statement about the two layouts, not about any model.
"""

from __future__ import annotations

import itertools

import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from bess.forecaster.evaluate import CoverageResult, rolling_origin_folds
from bess.forecaster.tune import (
    DEFAULT_GRID,
    INCUMBENT,
    REPORTING_LAYOUT,
    TUNING_TEST_DAYS,
    SharpnessCandidate,
    rank_candidates,
    tuning_folds,
)

_BAND = (0.85, 0.95)


def _result(coverage: float, mean_width: float, dev: float) -> CoverageResult:
    return CoverageResult(
        coverage=coverage,
        ci_low=coverage - 0.03,
        ci_high=coverage + 0.03,
        mean_width=mean_width,
        median_width=mean_width * 0.9,
        n_test_days=60,
        per_fold=(coverage,),
        by_hour=(coverage,) * 24,
        max_hour_deviation=dev,
    )


_scored = st.lists(
    st.tuples(
        st.floats(min_value=0.5, max_value=1.0),
        st.floats(min_value=1.0, max_value=500.0),
        st.floats(min_value=0.0, max_value=0.5),
    ),
    min_size=1,
    max_size=12,
)


def _grid(rows: list[tuple[float, float, float]]) -> list[tuple[dict, CoverageResult]]:
    """Give each recorded triple a distinct params dict, so candidates are separable."""
    return [
        ({**INCUMBENT, "n_estimators": 100 + 10 * i}, _result(cov, width, dev))
        for i, (cov, width, dev) in enumerate(rows)
    ]


@settings(max_examples=200, deadline=None)
@given(
    rows=_scored, inc=st.tuples(st.floats(0.85, 0.95), st.floats(1.0, 500.0), st.floats(0.0, 0.5))
)
def test_selected_always_satisfies_both_constraints(rows, inc):
    """Whatever the grid, the winner is in band and no worse per hour than the incumbent."""
    incumbent = SharpnessCandidate.from_result(INCUMBENT, _result(*inc))
    res = rank_candidates(_grid(rows), incumbent=incumbent, coverage_band=_BAND)

    assert _BAND[0] <= res.selected.coverage <= _BAND[1]
    assert res.selected.max_hour_deviation <= incumbent.max_hour_deviation


@settings(max_examples=200, deadline=None)
@given(
    rows=_scored, inc=st.tuples(st.floats(0.85, 0.95), st.floats(1.0, 500.0), st.floats(0.0, 0.5))
)
def test_selected_is_never_wider_than_the_incumbent(rows, inc):
    """The incumbent is always a candidate, so the search cannot lose to what ships."""
    incumbent = SharpnessCandidate.from_result(INCUMBENT, _result(*inc))
    res = rank_candidates(_grid(rows), incumbent=incumbent, coverage_band=_BAND)

    assert res.selected.mean_width <= incumbent.mean_width


@settings(max_examples=100, deadline=None)
@given(
    rows=st.lists(
        st.tuples(st.floats(0.85, 0.95), st.floats(1.0, 500.0), st.floats(0.0, 0.04)),
        min_size=2,
        max_size=6,
    )
)
def test_selection_is_invariant_to_grid_order(rows):
    """Permuting the grid leaves the winner unchanged: ties break deterministically.

    Without this, a re-ordered grid could return a different model at equal width,
    and the recorded search result would not reproduce.
    """
    incumbent = SharpnessCandidate.from_result(INCUMBENT, _result(0.90, 400.0, 0.05))
    grid = _grid(rows)
    base = rank_candidates(grid, incumbent=incumbent, coverage_band=_BAND).selected

    for perm in itertools.islice(itertools.permutations(grid), 12):
        got = rank_candidates(list(perm), incumbent=incumbent, coverage_band=_BAND).selected
        assert got.params == base.params
        assert got.mean_width == base.mean_width


@settings(max_examples=100, deadline=None)
@given(
    rows=_scored, inc=st.tuples(st.floats(0.85, 0.95), st.floats(1.0, 500.0), st.floats(0.0, 0.5))
)
def test_ranked_is_exactly_the_feasible_candidates_sorted(rows, inc):
    incumbent = SharpnessCandidate.from_result(INCUMBENT, _result(*inc))
    res = rank_candidates(_grid(rows), incumbent=incumbent, coverage_band=_BAND)

    widths = [c.mean_width for c in res.ranked]
    assert widths == sorted(widths)
    assert all(c.feasible for c in res.ranked)
    assert {id(c) for c in res.ranked} == {
        id(c) for c in (*res.all_candidates, res.incumbent) if c.feasible
    }


def test_the_default_grid_contains_the_incumbent():
    """The shipped model must be reachable by the search, not merely compared to it."""
    assert INCUMBENT in DEFAULT_GRID
    assert len(DEFAULT_GRID) == len(set(tuple(sorted(c.items())) for c in DEFAULT_GRID))


def _block(fold) -> set[pd.Timestamp]:
    return set(pd.date_range(fold.test_start, fold.test_end, freq="D"))


def test_no_tuning_test_block_intersects_a_reporting_test_block():
    """The whole leakage argument for this phase, asserted rather than inspected.

    Tuning blocks sit in the gaps between reporting blocks, so this is the property
    that keeps the reported width from being the width the winner was selected on. If
    either placement moves, it fails and the phase's selection is no longer clean.
    """
    days = pd.date_range("2021-01-01", "2025-09-30", freq="D", tz="UTC")
    reporting = rolling_origin_folds(days, **REPORTING_LAYOUT)
    tuning = tuning_folds(days)

    scored_by_gate = set().union(*(_block(f) for f in reporting))
    scored_by_search = set().union(*(_block(f) for f in tuning))

    assert not (scored_by_gate & scored_by_search)


def test_tuning_folds_match_the_reporting_regime():
    """Same block length and same training window as a reporting fold: only the placement differs.

    The 2021 placement the spec first proposed failed here in substance rather than in
    form: it scored a different regime on a shorter window, and the incumbent itself
    missed the coverage band there.
    """
    days = pd.date_range("2021-01-01", "2025-09-30", freq="D", tz="UTC")
    reporting = rolling_origin_folds(days, **REPORTING_LAYOUT)
    tuning = tuning_folds(days)

    assert len(tuning) == 12
    for fold in tuning:
        assert len(_block(fold)) == TUNING_TEST_DAYS
        assert (fold.test_start - fold.train_start).days == REPORTING_LAYOUT["train_days"]
        assert fold.train_end == fold.test_start  # exclusive train_end, no look-ahead

    # Spread across the reported years rather than bunched in one of them.
    years = {f.test_start.year for f in tuning}
    assert years == {f.test_start.year for f in reporting}


def test_tuning_folds_are_placed_deterministically():
    days = pd.date_range("2021-01-01", "2025-09-30", freq="D", tz="UTC")
    assert tuning_folds(days) == tuning_folds(days)
