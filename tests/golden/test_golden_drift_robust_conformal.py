"""Golden oracles for R2.1g: weighted conformal and adaptive conformal inference.

Spec: ``docs/specs/drift-robust-conformal.md`` § "Golden oracles" (oracles 2 to 8);
math: ``formulation-uncertainty.md`` §R2.1.

Both constructions are exact arithmetic on top of an exact recursion, so these are
hand-derived rather than statistical. Three of them carry most of the weight:

- **Oracle 3** pins that the ``+inf`` atom binds. Barber et al.'s Theorem 2a holds for
  a quantile taken over the calibration scores *plus* an atom at ``+inf`` carrying mass
  ``1 / (sum(w) + 1)``. Drop that atom, or fall back to ``max(scores)`` when it is
  selected, and the interval still looks reasonable while the guarantee it advertises
  is simply false. This is the failure mode that cannot be caught by eye.
- **Oracle 4** pins that weights outside ``[0, 1]`` are refused. The theorem is stated
  for ``w_i`` in ``[0, 1]``, and rescaling them is not a no-op: the ``+inf`` atom's mass
  is ``1 / (sum(w) + 1)``, so doubling every weight silently halves it.
- **Oracle 6** pins Proposition 4.1's right-hand side, including the ``gamma * T``
  denominator. It is the number every sequential run is scored against, so an error
  there would make the ACI gate unfalsifiable rather than merely wrong.

Oracle 1 (the shipped model is bitwise unchanged at ``weight_half_life_days=None``)
needs LightGBM and MAPIE and lives in ``tests/unit/test_forecaster_model.py``.

Pure numpy: no LightGBM or MAPIE, so these run in the CI tier.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from bess.forecaster.conformal import (
    AciState,
    aci_bound,
    aci_update,
    changepoint_gap_bound,
    decay_weights,
    drift_gap_bound,
    weighted_quantile,
)

_SCORES = np.array([1.0, 2.0, 3.0, 10.0])


def test_oracle2_weighted_quantile_lands_on_the_hand_computed_atom():
    """Four scores, hand-written weights, and the level exactly on an atom boundary.

    Unnormalized ``w = [0.2, 0.4, 0.6, 0.8]`` sums to 2.0, so the denominator is 3.0 and
    the normalized weights are ``[1, 2, 3, 4] / 15`` with ``1/3`` left on ``+inf``.
    The cumulative mass over the ascending scores is ``[1, 3, 6, 10] / 15``.

    At level 0.4 the cumulative mass reaches exactly ``6/15``, so the quantile is the
    atom **at** that boundary, 3.0. A hair above 0.4 it is the next atom, 10.0. Pinning
    both sides is the point: a `>` where the definition says `>=` passes every
    smooth test and fails only here.
    """
    weights = np.array([0.2, 0.4, 0.6, 0.8])

    assert weighted_quantile(_SCORES, weights, level=0.4) == 3.0
    assert weighted_quantile(_SCORES, weights, level=0.4 + 1e-12) == 10.0
    assert weighted_quantile(_SCORES, weights, level=2.0 / 3.0) == 10.0


def test_oracle3_the_infinite_atom_binds_and_is_returned_as_infinity():
    """When the ``+inf`` atom outweighs alpha, the honest answer is an infinite margin.

    ``w = [0.05] * 4`` sums to 0.2, so ``+inf`` carries ``1 / 1.2 = 0.833`` of the mass,
    far more than the 0.1 that a 90% interval may spend. No finite score can be the
    0.9 quantile, and the margin is genuinely infinite: with this little effective
    calibration data the construction has nothing to promise.

    Returning ``max(scores) = 10.0`` here would be the natural implementation slip and
    would produce a plausible-looking interval carrying no guarantee at all.
    """
    weights = np.full(4, 0.05)

    assert weighted_quantile(_SCORES, weights, level=0.9) == math.inf


def test_oracle4_a_weight_above_one_is_refused():
    """``w_i`` outside ``[0, 1]`` is a `ValueError`, not a silent renormalization.

    Theorem 2a is stated for weights in ``[0, 1]``. They are deliberately *not*
    normalized to sum to one, because the ``+inf`` atom's mass is ``1/(sum(w)+1)``:
    scaling the weights moves that mass rather than cancelling out, so "normalizing"
    them the way one normally would voids the bound.
    """
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        weighted_quantile(_SCORES, np.array([0.2, 0.4, 0.6, 1.5]), level=0.9)


def test_oracle4b_equal_weights_reproduce_the_split_conformal_order_statistic():
    """At rho = 1 the weighted quantile *is* R2.1's ``ceil((1-alpha)(n+1))``-th score.

    Not a separate construction that happens to agree: with every ``w_i = 1`` the
    normalized mass is ``1/(n+1)`` per atom, so the cumulative mass at the k-th smallest
    score is ``k/(n+1)`` and the smallest k reaching ``1-alpha`` is exactly the split
    conformal order statistic. This is what makes the incumbent a point in the family
    rather than a baseline outside it, and it is what oracle 1 then checks end to end.
    """
    rng = np.random.default_rng(0)
    scores = np.sort(rng.gamma(2.0, 5.0, size=99))
    ones = np.ones(99)

    for alpha in (0.1, 0.2, 0.5):
        k = math.ceil((1.0 - alpha) * (len(scores) + 1))
        assert weighted_quantile(scores, ones, level=1.0 - alpha) == scores[k - 1]


def test_oracle5_the_aci_recursion_walks_the_hand_computed_path():
    """A miss costs ``gamma * (1 - alpha)``; a hit pays back ``gamma * alpha``.

    With ``alpha = 0.1`` and ``gamma = 0.01`` a miss moves the level by ``-0.009`` and a
    hit by ``+0.001``, so a run with three misses in ten days ends at 0.080. Nine hits
    are needed to undo one miss, which is the whole asymmetry of the update and the
    reason it targets 10% misses rather than 50%.
    """
    state = AciState(alpha=0.1, alpha_emitted=0.1, alpha_target=0.1, gamma=0.01, clamp=(0.01, 0.5))
    errs = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    expected = [0.091, 0.092, 0.093, 0.084, 0.085, 0.086, 0.087, 0.088, 0.079, 0.080]

    path = []
    for err in errs:
        state = aci_update(state, err=err)
        path.append(state.alpha)

    assert path == pytest.approx(expected, abs=1e-12)
    assert state.n_updates == 10
    assert state.n_clamped == 0


def test_oracle6_the_proposition_41_bound_includes_the_gamma_t_denominator():
    """``(max{alpha_1, 1-alpha_1} + gamma) / (gamma * T)``, evaluated by hand.

    At ``alpha_1 = 0.1``, ``gamma = 0.01``, ``T = 100`` that is ``0.91 / 1 = 0.91``: the
    bound is vacuous at this run length, which is the honest reading and exactly why the
    gate scores a multi-year sequential run rather than a 5-day block. Dropping the
    ``gamma`` from the denominator would give 0.0091 and make the gate look satisfiable
    on a fortnight.
    """
    assert aci_bound(alpha_1=0.1, gamma=0.01, n_updates=100) == pytest.approx(0.91, abs=1e-12)
    assert aci_bound(alpha_1=0.1, gamma=0.01, n_updates=10_000) == pytest.approx(0.0091, abs=1e-12)
    # gamma = 0 is the non-adaptive arm: the recursion never moves, so there is no
    # long-run claim to make and the bound is infinite rather than a division error.
    assert aci_bound(alpha_1=0.1, gamma=0.0, n_updates=10_000) == math.inf


def test_oracle7_a_one_half_life_old_changepoint_costs_exactly_half_the_coverage():
    """Theorem 2a's changepoint corollary: gap <= rho ** k, with k in points.

    A 7-day half-life and a regime break 7 days back gives ``rho ** 168 = 0.5`` on
    hourly data, whatever ``rho`` itself is. Expressing the knob as a half-life in days
    is what makes that readable; the per-hour ``rho = 0.9995...`` is not a number anyone
    can reason about.
    """
    assert changepoint_gap_bound(half_life_days=7.0, lag_days=7.0) == pytest.approx(0.5, abs=1e-12)
    assert changepoint_gap_bound(half_life_days=7.0, lag_days=14.0) == pytest.approx(
        0.25, abs=1e-12
    )
    assert changepoint_gap_bound(half_life_days=14.0, lag_days=7.0) == pytest.approx(
        2.0**-0.5, abs=1e-12
    )


def test_oracle8_the_incumbent_promises_nothing_off_exchangeability():
    """Unweighted conformal has a gap bound of 1.0, not 0.0.

    This is the oracle that states the phase's motivation as arithmetic. At ``rho = 1``
    the changepoint bound is ``1 ** k = 1``, so Theorem 2a degrades to "coverage is at
    least ``1 - alpha - 1``", which is no claim at all, and the Lipschitz bound
    ``2 * epsilon / (1 - rho)`` is infinite. That is the correct reading of the shipped
    forecaster under a regime shift, and the code returns it rather than a comfortable
    zero.
    """
    assert changepoint_gap_bound(half_life_days=None, lag_days=7.0) == 1.0
    assert changepoint_gap_bound(half_life_days=None, lag_days=3650.0) == 1.0
    assert drift_gap_bound(half_life_days=None, epsilon=1e-6) == math.inf

    # A finite half-life makes both bounds informative again.
    assert drift_gap_bound(half_life_days=7.0, epsilon=1e-6) < 1.0


def test_decay_weights_are_geometric_most_recent_last_and_bounded_by_one():
    """``w_i = rho ** (n + 1 - i)``: the newest score carries ``rho``, not 1.0.

    The paper indexes calibration points in time order with the test point at ``n+1``,
    so the most recent calibration point is one step from the test point and carries
    ``rho ** 1``. Getting this off by one would shift the whole weight profile by an
    hour, which no coverage number would reveal.
    """
    w = decay_weights(4, half_life_days=1.0 / 24.0)  # half-life of exactly one hour

    assert w == pytest.approx([0.0625, 0.125, 0.25, 0.5], abs=1e-12)
    assert np.all((w >= 0.0) & (w <= 1.0))
    assert decay_weights(5, half_life_days=None) == pytest.approx(np.ones(5))
