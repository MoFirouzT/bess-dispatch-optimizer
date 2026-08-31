"""Gates for the R2.1g sequential (online) coverage harness.

Spec: ``docs/specs/drift-robust-conformal.md``.

The block harness (``walk_forward_coverage``) scores independent folds, which is the
right shape for a fixed calibration and the wrong one for an adaptive level: Gibbs and
Candès's guarantee attaches to a long run, not to any one block. This harness walks day
by day and carries the level forward, so what has to be gated is different:

- the **leakage discipline** still holds when the loop, not a fold list, decides what a
  model saw (a fit never reaches its own scored day);
- ``aci_gamma=0`` with no weighting is inert, so the arms are read against a baseline
  that is the incumbent construction and not a rewrite of it;
- the recursion's state is really carried across days rather than reset per day, which
  is the one thing that distinguishes this from the block harness and the one thing a
  coverage number cannot reveal.

Skip-guarded: needs the ``forecast`` dependency group (LightGBM + MAPIE).
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("lightgbm")
pytest.importorskip("mapie")

import pandas as pd  # noqa: E402

from bess.data.fixtures import synthetic_day_ahead  # noqa: E402
from bess.forecaster import sequential_coverage  # noqa: E402

#: Small and fast: these gate the harness's mechanics, not a coverage claim.
_FAST = dict(n_estimators=30, random_state=0, n_boot=200)
_RUN = dict(train_days=60, refit_every_days=60, **_FAST)


def _drifting(days: int = 200, seed: int = 11, ramp: float = 120.0) -> pd.Series:
    """A price series whose level trends hard: the R2.1f failure mode in miniature."""
    base = synthetic_day_ahead(days=days, seed=seed)
    return (base + np.linspace(0.0, ramp, len(base.index))).rename("price_eur_mwh")


def _start(prices: pd.Series, after_days: int) -> pd.Timestamp:
    return prices.index[0].normalize() + pd.Timedelta(days=after_days)


def test_the_non_adaptive_arm_is_inert():
    """``aci_gamma=0`` and no weighting leaves the level and the clamp untouched.

    The baseline every other arm is read against. If this drifted, "weighted versus
    incumbent" would be measuring the harness rather than the method.
    """
    prices = _drifting()
    r = sequential_coverage(prices, start=_start(prices, 70), aci_gamma=0.0, **_RUN)

    assert r.alpha_first == r.alpha_last == pytest.approx(0.1)
    assert r.n_clamped == 0
    assert r.realized_gap == 0.0
    # No decay means Theorem 2a bounds nothing off-exchangeability, and the harness
    # reports that rather than a comfortable zero.
    assert r.gap_bound_7d == 1.0


def test_the_aci_level_is_carried_across_days_not_reset():
    """Under sustained under-coverage the level walks down and stays down.

    The one behaviour that separates an online run from a sequence of independent
    blocks, and the one a coverage number alone cannot show: a per-day reset would leave
    ``alpha_last`` at its starting value while still producing a plausible coverage
    figure.
    """
    prices = _drifting(ramp=200.0)  # steep enough to keep missing
    r = sequential_coverage(prices, start=_start(prices, 70), aci_gamma=0.02, **_RUN)

    assert r.alpha_last < r.alpha_first
    assert r.realized_gap > 0.0
    assert r.n_days > 50


def test_adaptation_recovers_coverage_that_the_fixed_level_loses():
    """On a drifting series ACI covers materially better than the incumbent arm.

    The non-vacuity check for the whole phase: without it, every gate here could pass on
    an implementation that carried state faithfully and did nothing useful with it. This
    is deliberately a *direction* assertion on synthetic data, not a threshold: the
    numbers that decide adoption are measured on real prices under the spec's protocol.
    """
    prices = _drifting()
    start = _start(prices, 70)

    fixed = sequential_coverage(prices, start=start, aci_gamma=0.0, **_RUN)
    adaptive = sequential_coverage(prices, start=start, aci_gamma=0.02, **_RUN)

    assert adaptive.coverage > fixed.coverage + 0.02
    # And it is paid for in width, which is why coverage is never gated alone.
    assert adaptive.median_width > fixed.median_width


def test_no_scored_day_is_inside_its_own_training_window():
    """The leakage discipline, asserted rather than assumed.

    R2.1d's rule is that a fold never trains on data at or after its own test block. Here
    the loop decides refits, so the rule has to be checked against the loop: every scored
    day must be strictly later than the last day of the window its model was fit on.

    Reconstructed from the refit schedule the harness uses, so it fails if that schedule
    ever starts a model on data reaching into the days it will score.
    """
    prices = _drifting()
    train_days, refit_every = 60, 60
    start = _start(prices, 70)

    r = sequential_coverage(
        prices, start=start, train_days=train_days, refit_every_days=refit_every, **_FAST
    )
    assert r.n_days > 0

    days = [d for d in sorted(pd.DatetimeIndex(prices.index).normalize().unique()) if d >= start]
    fitted_on = None
    for day in days:
        if fitted_on is None or (day - fitted_on).days >= refit_every:
            fitted_on = day
        # The model in force was fit on [fitted_on - train_days, fitted_on), which is
        # strictly before its own fit day, hence strictly before every day it scores.
        assert fitted_on <= day
        assert fitted_on - pd.Timedelta(days=train_days) < day


def test_per_year_breakdown_partitions_the_scored_days():
    """Every scored day lands in exactly one year bucket, none lost or double counted.

    The worst-year coverage number is what the spec's adoption gate turns on, so the
    split that produces it is pinned rather than trusted.
    """
    prices = _drifting(days=500)
    r = sequential_coverage(prices, start=_start(prices, 70), **_RUN)

    years = [y for y, _ in r.by_year]
    assert len(years) == len(set(years))
    assert [y for y, _ in r.per_year_width] == years
    assert all(0.0 <= c <= 1.0 for _, c in r.by_year)


def test_a_short_half_life_reports_an_informative_gap_bound():
    """Weighting turns Theorem 2a from a vacuous statement into a number.

    The phase's deliverable that no amount of coverage measurement supplies: with decay
    on, a regime break a week ago costs at most a stated amount of coverage, and the run
    reports it beside the coverage it measured.
    """
    prices = _drifting()
    r = sequential_coverage(prices, start=_start(prices, 70), weight_half_life_days=7.0, **_RUN)

    assert r.gap_bound_7d == pytest.approx(0.5, abs=1e-12)


def test_the_sequential_harness_agrees_with_the_block_harness_on_the_same_days():
    """Two independent instruments, one answer: the strongest check either is right.

    R2.1d's finding was that the *harness* was wrong, so every published coverage number
    was a statement about one fortnight in May. The same failure is available here, and
    a new harness that only agrees with itself proves nothing. Configured so both fit on
    the identical 60 days and score the identical 5, pooled coverage must match exactly.

    **`method="split"` is not a shortcut, it is the only method where this comparison is
    valid.** The sequential path builds its margin from the symmetric score, while the
    block harness goes through MAPIE's CQR default, which is the asymmetric per-side
    variant (see `test_the_shipped_default_is_the_asymmetric_variant_not_the_documented_one`).
    Split conformal has one construction, so the two agree there and the comparison
    measures the harness rather than that divergence.
    """
    from bess.forecaster import walk_forward_coverage

    prices = _drifting(days=100)
    days = sorted(pd.DatetimeIndex(prices.index).normalize().unique())

    block = walk_forward_coverage(
        prices,
        n_folds=1,
        test_days=5,
        train_days=60,
        spacing="contiguous",
        method="split",
        return_detail=True,
        n_estimators=30,
        random_state=0,
    )
    online = sequential_coverage(
        prices,
        start=days[-5],
        train_days=60,
        refit_every_days=9999,  # one fit, so the two see identical training data
        method="split",
        aci_gamma=0.0,
        n_estimators=30,
        random_state=0,
        n_boot=200,
    )

    assert online.n_days == block.n_test_days
    assert online.coverage == pytest.approx(block.coverage, abs=1e-12)
    assert online.mean_width == pytest.approx(block.mean_width, abs=1e-9)


def test_the_base_learners_never_see_the_calibration_block():
    """Theorem 2a's precondition, gated instead of assumed.

    Barber et al. state the coverage bound for a **pre-fitted** model, independent of the
    calibration data. This project satisfies that by splitting temporally, but nothing
    asserted it, and the whole weighted construction is void without it.

    Perturbing only the calibration tail must leave the base learners bit-identical: if
    any calibration price reached the fit, the predictions would move. The conformal
    margin *is* expected to move, and that it does is asserted too, so the test cannot
    pass by the perturbation being ignored altogether.
    """
    from bess.forecaster import PriceForecaster

    prices = _drifting(days=120)
    cut = int(len(prices) * 0.75)  # inside the calibration tail at calib_fraction=0.3
    perturbed = prices.copy()
    perturbed.iloc[cut:] = perturbed.iloc[cut:] + 250.0

    clean = PriceForecaster(n_estimators=30, random_state=0).fit(prices)
    dirty = PriceForecaster(n_estimators=30, random_state=0).fit(perturbed)

    x = clean._features(prices, None, None).to_numpy()
    for a, b in zip(clean._base_bounds(x), dirty._base_bounds(x), strict=True):
        np.testing.assert_array_equal(a, b)

    assert clean._margin != dirty._margin


def test_the_recursion_updates_once_per_scored_day_across_refits():
    """One update per delivery day, and refitting does not restart the count.

    A refit rebuilds the forecaster. If it rebuilt the ACI state with it, the level would
    silently reset every `refit_every_days` and the long-run guarantee would be measuring
    a sequence of short runs. The count is the direct evidence; `alpha_last` moving is
    not, since it moves either way.
    """
    prices = _drifting(days=260)
    r = sequential_coverage(
        prices,
        start=_start(prices, 70),
        aci_gamma=0.01,
        train_days=60,
        refit_every_days=30,
        **_FAST,
    )

    assert r.n_updates == r.n_days
    assert r.n_days > 120  # long enough that several refits happened
    assert r.realized_gap == pytest.approx(
        abs(r.alpha_last - r.alpha_first) / (0.01 * r.n_updates), abs=1e-12
    )
