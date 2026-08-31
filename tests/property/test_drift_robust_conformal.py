"""Property gates for R2.1g: weighted conformal and adaptive conformal inference.

Spec: ``docs/specs/drift-robust-conformal.md`` § "Property tests".

The two ACI gates here are unusual for this repo, and deliberately so. Gibbs and
Candès's Lemma 4.1 and Proposition 4.1 are **deterministic, almost-sure statements
with no assumption on the data-generating distribution**: they hold for every
miscoverage sequence, including one chosen to break them. So they are gated by
generating adversarial sequences rather than by measuring a statistic on plausible
ones. A counterexample here is a bug, never bad luck, which is what separates this
from the coverage gate next door.

The weighted-conformal gates are ordinary monotonicity invariants, plus the one that
matters most in practice: at ``half_life_days=None`` the construction must be the
shipped one, bitwise, on every input rather than on the golden seed.

Pure numpy: no LightGBM or MAPIE, so these run in the CI tier.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from bess.forecaster.conformal import (
    AciState,
    aci_bound,
    aci_realized_gap,
    aci_update,
    changepoint_gap_bound,
    decay_weights,
    weighted_quantile,
)

_ERRS = st.lists(st.floats(min_value=0.0, max_value=1.0), min_size=1, max_size=400)
_GAMMA = st.floats(min_value=1e-4, max_value=0.5)
_ALPHA = st.floats(min_value=0.01, max_value=0.99)


def _run(errs, *, alpha, gamma, clamp=(-math.inf, math.inf)):
    state = AciState(alpha=alpha, alpha_emitted=alpha, alpha_target=alpha, gamma=gamma, clamp=clamp)
    for err in errs:
        state = aci_update(state, err=err)
    return state


def _realizable(errs, *, alpha, gamma):
    """Replay a sequence, forcing the two outcomes the *unclamped* algorithm cannot avoid.

    ``err_t`` is an observation, not a free choice: at a level below 0 the interval is
    the whole line, so the day cannot miss, and above 1 it is empty, so it cannot hit.
    Lemma 4.1's proof turns on exactly that feedback, so a sequence ignoring it is not
    something the algorithm can produce and proves nothing about the algorithm.
    """
    state = AciState(
        alpha=alpha,
        alpha_emitted=alpha,
        alpha_target=alpha,
        gamma=gamma,
        clamp=(-math.inf, math.inf),
    )
    realized = []
    for drawn in errs:
        if state.alpha_emitted < 0.0:
            err = 0.0
        elif state.alpha_emitted > 1.0:
            err = 1.0
        else:
            err = drawn
        realized.append(err)
        state = aci_update(state, err=err)
        yield state, realized


@settings(max_examples=200, deadline=None)
@given(errs=_ERRS, alpha=_ALPHA, gamma=_GAMMA)
def test_the_telescoping_identity_holds_for_every_sequence(errs, alpha, gamma):
    """``|mean(err) - alpha| == |alpha_final - alpha_1| / (gamma * T)``, exactly.

    Unconditional, and the strongest of the three ACI gates: it needs no realizability
    assumption, no clamp discipline, and no bound on the iterate. Proposition 4.1 is
    this identity plus an a-priori bound on how far the iterate can have travelled, and
    the identity is the half that survives clamping. It is therefore what the sequential
    harness reports, in place of a bound that quietly stops being true.
    """
    state = _run(errs, alpha=alpha, gamma=gamma)
    realized = float(np.mean(errs))

    assert abs(realized - alpha) == pytest.approx(
        aci_realized_gap(alpha_1=alpha, alpha_final=state.alpha, gamma=gamma, n_updates=len(errs)),
        abs=1e-9,
    )


@settings(max_examples=200, deadline=None)
@given(errs=_ERRS, alpha=_ALPHA, gamma=_GAMMA)
def test_proposition_41_holds_on_realizable_unclamped_sequences(errs, alpha, gamma):
    """The published long-run bound, on sequences the unclamped algorithm can produce.

    ``|mean(err) - alpha| <= (max{alpha_1, 1-alpha_1} + gamma) / (gamma * T)``.

    Adversarial in everything the algorithm does not determine: the miss rate is free
    wherever the level is in ``[0, 1]``, so this covers all-misses, no-misses, and any
    burst pattern between. What it does not cover is a level outside ``[0, 1]``
    contradicting its own interval, which is not a run but an inconsistency.
    """
    for _state, realized in _realizable(errs, alpha=alpha, gamma=gamma):
        assert (
            abs(float(np.mean(realized)) - alpha)
            <= aci_bound(alpha_1=alpha, gamma=gamma, n_updates=len(realized)) + 1e-9
        )


@settings(max_examples=200, deadline=None)
@given(errs=_ERRS, alpha=_ALPHA, gamma=_GAMMA)
def test_lemma_41_keeps_the_unclamped_iterate_in_its_stated_range(errs, alpha, gamma):
    """The iterate never leaves ``[-gamma, 1 + gamma]`` on a realizable run.

    Our day-batched ``err`` in ``[0, 1]`` preserves both saturation facts (24 hits give a
    rate of 0, 24 misses a rate of 1), which is the step the spec's re-derivation makes
    explicit, and this is the gate on that reasoning.
    """
    for state, _ in _realizable(errs, alpha=alpha, gamma=gamma):
        assert -gamma - 1e-12 <= state.alpha <= 1.0 + gamma + 1e-12


def test_clamping_can_unbind_the_iterate_and_that_is_why_the_bound_is_not_gated():
    """The clamp does not pause Lemma 4.1, it removes the feedback the lemma rests on.

    Found by the property test above, not reasoned to in advance. With the emitted level
    pinned inside ``clamp``, a level above 1 no longer produces an empty interval, so
    nothing forces a miss and nothing pulls the iterate back: it can travel arbitrarily
    far, and Proposition 4.1's a-priori bound stops applying. This is stronger than the
    spec's original wording, which said the guarantee was void only while the clamp bound.

    Sixty clean days at the clamped level walk the iterate past ``1 + gamma``, which the
    unclamped recursion cannot do. Gated as a demonstration so the limitation cannot be
    quietly lost, and it is why the sequential harness reads the exact identity and gates
    the clamp binding rate instead of asserting the bound.
    """
    state = AciState(alpha=0.9, alpha_emitted=0.5, alpha_target=0.9, gamma=0.05, clamp=(0.01, 0.5))
    for _ in range(60):
        state = aci_update(state, err=0.0)  # a clamped interval that keeps covering

    assert state.alpha > 1.0 + state.gamma
    assert state.n_clamped == 60


@settings(max_examples=50, deadline=None)
@given(errs=_ERRS, alpha=_ALPHA)
def test_gamma_zero_is_the_non_adaptive_arm_exactly(errs, alpha):
    """``gamma = 0`` leaves the level untouched and clamps nothing."""
    state = _run(errs, alpha=alpha, gamma=0.0, clamp=(0.01, 0.5))

    assert state.alpha == alpha
    assert state.n_clamped == (0 if 0.01 <= alpha <= 0.5 else len(errs))


@settings(max_examples=100, deadline=None)
@given(errs=_ERRS, gamma=st.floats(min_value=0.01, max_value=0.5))
def test_the_clamp_is_counted_exactly_when_it_moves_the_emitted_level(errs, gamma):
    """``n_clamped`` counts the steps where the emitted level differs from the iterate.

    Clamping voids Proposition 4.1 for as long as it binds, so the count is not
    bookkeeping: it is the number the gate reads to decide whether an arm adapted or
    merely saturated. An arm that spends its run pinned at the clamp is a fixed-level
    arm wearing ACI's name, and this is what makes that visible.
    """
    clamp = (0.05, 0.2)
    state = AciState(alpha=0.1, alpha_emitted=0.1, alpha_target=0.1, gamma=gamma, clamp=clamp)
    counted = 0
    for err in errs:
        state = aci_update(state, err=err)
        assert clamp[0] <= state.alpha_emitted <= clamp[1]
        if state.alpha_emitted != state.alpha:
            counted += 1
        assert state.n_clamped == counted


@settings(max_examples=100, deadline=None)
@given(
    scores=st.lists(
        st.floats(min_value=0.0, max_value=1e4, allow_nan=False), min_size=9, max_size=200
    ),
    alpha=st.floats(min_value=0.05, max_value=0.5),
)
def test_equal_weights_reproduce_split_conformal_on_every_input(scores, alpha):
    """``half_life_days=None`` is R2.1's order statistic, not an approximation of it.

    The opt-in identity, generated rather than seeded: the golden oracle pins one case,
    and this pins that no input reaches a different branch. Without it the weighted path
    could agree on the golden scores and diverge on ties, duplicates, or zeros.
    """
    arr = np.array(sorted(scores))
    k = math.ceil((1.0 - alpha) * (len(arr) + 1))
    expected = arr[k - 1] if k <= len(arr) else math.inf

    ones = decay_weights(len(arr), half_life_days=None)

    assert weighted_quantile(arr, ones, level=1.0 - alpha) == expected


@settings(max_examples=100, deadline=None)
@given(
    scores=st.lists(
        st.floats(min_value=0.0, max_value=1e4, allow_nan=False), min_size=9, max_size=120
    ),
    a=st.floats(min_value=0.05, max_value=0.5),
    b=st.floats(min_value=0.05, max_value=0.5),
)
def test_the_margin_is_non_increasing_in_alpha(scores, a, b):
    """A larger miscoverage budget never buys a wider interval."""
    assume(a < b)
    arr = np.array(scores)
    w = decay_weights(len(arr), half_life_days=30.0)

    assert weighted_quantile(arr, w, level=1 - a) >= weighted_quantile(arr, w, level=1 - b)


@settings(max_examples=100, deadline=None)
@given(
    n=st.integers(min_value=30, max_value=300),
    short=st.floats(min_value=1.0, max_value=20.0),
    long=st.floats(min_value=21.0, max_value=400.0),
)
def test_shortening_the_half_life_widens_the_margin_on_a_rising_score_path(n, short, long):
    """With scores rising over time, concentrating weight on recent ones cannot shrink it.

    Two effects push the same way and this pins both: recent (larger) scores gain mass,
    and the total weight falls so the ``+inf`` atom gains mass too. A implementation that
    renormalized the weights to sum to one would lose the second effect entirely and
    could fail here, which is the point of testing the pair together.
    """
    scores = np.linspace(1.0, 100.0, n)

    fast = weighted_quantile(scores, decay_weights(n, half_life_days=short), level=0.9)
    slow = weighted_quantile(scores, decay_weights(n, half_life_days=long), level=0.9)

    assert fast >= slow


@settings(max_examples=100, deadline=None)
@given(
    half_life=st.floats(min_value=1.0, max_value=365.0),
    lag_a=st.floats(min_value=1.0, max_value=200.0),
    lag_b=st.floats(min_value=1.0, max_value=200.0),
)
def test_the_changepoint_gap_bound_decays_with_distance_and_stays_a_probability(
    half_life, lag_a, lag_b
):
    """Older breaks cost less coverage, and the bound never leaves ``[0, 1]``."""
    assume(lag_a < lag_b)

    near = changepoint_gap_bound(half_life_days=half_life, lag_days=lag_a)
    far = changepoint_gap_bound(half_life_days=half_life, lag_days=lag_b)

    assert 0.0 <= far <= near <= 1.0
