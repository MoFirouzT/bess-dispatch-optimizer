"""Property tests for R2.8: seed reproducibility.

Contract: docs/specs/draw-noise.md § "Property tests".

The goldens pin hand-chosen cases; these pin the invariants over arbitrary ones. The
load-bearing one is label invariance: seeds are *names* for runs, so relabelling them
must not move a published width.
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bess.studies import summarize_across_seeds

_MEDIANS = st.lists(
    st.floats(min_value=-1e4, max_value=1e4, allow_nan=False, allow_infinity=False),
    min_size=2,
    max_size=30,
)


@given(values=_MEDIANS)
@settings(max_examples=100, deadline=None)
def test_ordering_invariants_hold(values) -> None:
    """min <= mean <= max, and the spread is never negative."""
    s = summarize_across_seeds(dict(enumerate(values)))

    assert s.n_seeds == len(values)
    assert s.min_median <= s.mean_median + 1e-9
    assert s.mean_median <= s.max_median + 1e-9
    assert s.spread >= 0.0
    assert s.sd_median >= 0.0


@given(values=_MEDIANS, offset=st.integers(min_value=-10_000, max_value=10_000))
@settings(max_examples=60, deadline=None)
def test_seed_labels_do_not_affect_the_result(values, offset) -> None:
    """Rekeying the seeds leaves every field identical.

    Seeds name runs; they are not an ordering and carry no magnitude. A width that
    changed when someone ran seeds 100-109 instead of 0-9 would be reporting the labels.
    """
    a = summarize_across_seeds(dict(enumerate(values)))
    b = summarize_across_seeds({i + offset: v for i, v in enumerate(values)})

    assert a == b


@given(values=_MEDIANS)
@settings(max_examples=60, deadline=None)
def test_zero_spread_exactly_when_every_median_agrees(values) -> None:
    """`spread == 0` is equivalent to full agreement, in both directions."""
    s = summarize_across_seeds(dict(enumerate(values)))

    assert (s.spread == 0.0) == (len(set(values)) == 1)


@given(values=_MEDIANS, shift=st.floats(min_value=-500, max_value=500, allow_nan=False))
@settings(max_examples=60, deadline=None)
def test_width_is_translation_invariant(values, shift) -> None:
    """Shifting every median by a constant moves the centre, not the width.

    The width must describe dispersion alone: a study whose euros all moved up by 10
    is not thereby less reproducible.
    """
    a = summarize_across_seeds(dict(enumerate(values)))
    b = summarize_across_seeds({i: v + shift for i, v in enumerate(values)})

    assert b.spread == pytest.approx(a.spread, abs=1e-6)
    assert b.sd_median == pytest.approx(a.sd_median, abs=1e-6)
    assert b.mean_median == pytest.approx(a.mean_median + shift, abs=1e-6)


@given(values=_MEDIANS)
@settings(max_examples=40, deadline=None)
def test_matches_numpy_on_the_same_inputs(values) -> None:
    """The summary is exactly numpy's, so no bespoke arithmetic hides in it."""
    v = np.asarray(values, dtype=float)
    s = summarize_across_seeds(dict(enumerate(values)))

    assert s.mean_median == pytest.approx(float(v.mean()), abs=1e-9)
    assert s.sd_median == pytest.approx(float(v.std(ddof=0)), abs=1e-9)
    assert s.min_median == pytest.approx(float(v.min()), abs=1e-9)
    assert s.max_median == pytest.approx(float(v.max()), abs=1e-9)
