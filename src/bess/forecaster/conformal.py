"""Drift-robust conformal calibration: weighted quantiles and ACI (R2.1g).

Spec: ``docs/specs/drift-robust-conformal.md``; theory summary:
``formulation-uncertainty.md`` §R2.1.

R2.1's coverage guarantee holds for **exchangeable** data, and day-ahead prices are
not exchangeable: R2.1f measured pooled coverage falling from 0.897 in 2024 to 0.791
across the 2021 crisis ramp. This module holds the two published constructions that
survive that, each fixing a different half of the problem:

- **Weighted conformal** (Barber, Candès, Ramdas & Tibshirani 2023) fixes the
  *calibration set*. Old scores get geometrically less weight, and the coverage
  shortfall is bounded by a computable quantity instead of left unstated.
- **Adaptive conformal inference** (Gibbs & Candès 2021) fixes the *target level*. It
  watches realized misses and moves the nominal level to compensate, with a long-run
  guarantee that holds under arbitrary distribution shift.

Both modify one scalar, the conformal margin, so they compose: take the weighted
quantile at level ``1 - alpha_t``.

Pure numpy: no LightGBM or MAPIE, so the gates on this module run without the
``forecast`` dependency group.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

#: Hours per day, the unit conversion between a configured half-life and the per-point
#: decay. Weights are per calibration point; a half-life in days is what a reader can
#: reason about, and ``rho = 0.9995`` is not.
_HOURS_PER_DAY = 24.0


def _rho(half_life_days: float | None, dt_h: float = 1.0) -> float:
    """Per-point decay for a half-life in days. ``None`` gives 1.0 (no decay)."""
    if half_life_days is None:
        return 1.0
    if half_life_days <= 0.0:
        raise ValueError(f"half_life_days must be positive or None; got {half_life_days}")
    if dt_h <= 0.0:
        raise ValueError(f"dt_h must be positive; got {dt_h}")
    return float(2.0 ** (-dt_h / (half_life_days * _HOURS_PER_DAY)))


def decay_weights(n: int, *, half_life_days: float | None, dt_h: float = 1.0) -> np.ndarray:
    """Geometric weights ``w_i = rho ** (n + 1 - i)``, oldest first, most recent last.

    The paper indexes the calibration points in time order with the *test* point at
    ``n+1``, so the most recent calibration point is one step away and carries
    ``rho ** 1``, not 1.0. That off-by-one is invisible in any coverage number, so it is
    pinned by a golden oracle.

    ``half_life_days=None`` gives all-ones, which is R2.1's unweighted construction
    exactly rather than an approximation of it.
    """
    if n < 1:
        raise ValueError(f"n must be >= 1; got {n}")
    rho = _rho(half_life_days, dt_h)
    exponents = np.arange(n, 0, -1, dtype=float)  # n, n-1, ..., 1
    return np.asarray(rho**exponents, dtype=float)


def weighted_quantile(scores: np.ndarray, weights: np.ndarray, *, level: float) -> float:
    """Barber et al. eq. 13: the ``level`` quantile of the scores plus a ``+inf`` atom.

    The atom at ``+inf`` carries mass ``1 / (sum(w) + 1)`` and is what makes the bound
    finite-sample. When it is the atom the level lands on, the margin is genuinely
    infinite: the weights have discarded so much of the calibration set that the
    construction has nothing left to promise. ``inf`` is returned rather than the
    largest score, because the fallback would produce a plausible interval carrying no
    guarantee.

    Weights must lie in ``[0, 1]`` (the theorem's condition) and are deliberately *not*
    renormalized to sum to one: the ``+inf`` atom's mass depends on ``sum(w)``, so
    rescaling moves it rather than cancelling out.
    """
    s = np.asarray(scores, dtype=float)
    w = np.asarray(weights, dtype=float)
    if s.ndim != 1 or w.ndim != 1:
        raise ValueError("scores and weights must be 1-D")
    if s.shape != w.shape:
        raise ValueError(f"scores and weights must align; got {s.shape} and {w.shape}")
    if s.size == 0:
        raise ValueError("no calibration scores")
    if np.isnan(s).any():
        raise ValueError("scores contain NaN")
    if not np.all((w >= 0.0) & (w <= 1.0)):
        raise ValueError(
            "weights must lie in [0, 1] (Barber et al. Thm 2a); rescaling them is not a "
            "no-op, because the +inf atom carries mass 1 / (sum(w) + 1)"
        )
    if not 0.0 < level < 1.0:
        raise ValueError(f"level must be in (0, 1); got {level}")

    denom = float(w.sum()) + 1.0
    order = np.argsort(s, kind="stable")
    cumulative = np.cumsum(w[order]) / denom

    # Q_level(F) = inf{x : F(x) >= level}; the +inf atom holds the remaining mass, so
    # falling off the end of the finite atoms is the infinite case, not an error.
    idx = int(np.searchsorted(cumulative, level, side="left"))
    if idx >= s.size:
        return math.inf
    return float(s[order][idx])


def split_score(y: np.ndarray, point: np.ndarray) -> np.ndarray:
    """Split-conformal nonconformity ``|y - mu_hat(x)|`` (§R2.1)."""
    return np.abs(np.asarray(y, dtype=float) - np.asarray(point, dtype=float))


def cqr_score(y: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> np.ndarray:
    """CQR nonconformity ``max{q_lo(x) - y, y - q_hi(x)}`` (§R2.1).

    Signed by construction: negative inside the quantile band, positive outside, so the
    conformal step can tighten an over-wide band as well as widen a narrow one.
    """
    y = np.asarray(y, dtype=float)
    return np.maximum(np.asarray(lower, dtype=float) - y, y - np.asarray(upper, dtype=float))


def changepoint_gap_bound(*, half_life_days: float | None, lag_days: float) -> float:
    """Theorem 2a's coverage gap under a changepoint ``lag_days`` ago: ``rho ** k``.

    Coverage is at least ``1 - alpha - gap``. At ``half_life_days=None`` (rho = 1) the
    gap is 1.0, so the guarantee degrades to "coverage is at least ``-alpha``", which is
    no claim at all. That is the correct reading of the shipped unweighted forecaster
    under a regime shift, and it is returned rather than a comfortable zero.
    """
    if lag_days < 0.0:
        raise ValueError(f"lag_days must be >= 0; got {lag_days}")
    rho = _rho(half_life_days)
    if rho >= 1.0:
        return 1.0
    return float(min(1.0, rho ** (lag_days * _HOURS_PER_DAY)))


def drift_gap_bound(*, half_life_days: float | None, epsilon: float) -> float:
    """Theorem 2a's coverage gap under Lipschitz drift: ``2 * epsilon / (1 - rho)``.

    ``epsilon`` is the per-point bound on the total-variation distance between a
    calibration point's distribution and the test point's. Infinite at rho = 1, for the
    same reason as above: unweighted conformal bounds nothing off-exchangeability.
    """
    if epsilon < 0.0:
        raise ValueError(f"epsilon must be >= 0; got {epsilon}")
    rho = _rho(half_life_days)
    if rho >= 1.0:
        return math.inf
    return float(min(1.0, 2.0 * epsilon / (1.0 - rho)))


@dataclass(frozen=True)
class AciState:
    """One step of the adaptive conformal recursion (Gibbs & Candès eq. 2).

    ``alpha`` is the unclamped iterate the guarantee is stated for; ``alpha_emitted`` is
    the level the interval was actually built at. They differ only when the clamp binds,
    and ``n_clamped`` counts exactly those steps.

    That count matters more than it looks. Clamping does not merely pause Proposition
    4.1, it removes the feedback the proposition rests on: with the emitted level pinned
    inside ``clamp``, a level above 1 no longer produces an empty interval, so nothing
    forces a miss and the iterate can travel arbitrarily far. See
    :func:`aci_realized_gap`, which is what the gate reads instead.
    """

    alpha: float
    alpha_emitted: float
    alpha_target: float
    gamma: float
    clamp: tuple[float, float] = (0.01, 0.5)
    n_updates: int = 0
    n_clamped: int = 0


def aci_update(state: AciState, *, err: float) -> AciState:
    """``alpha_{t+1} = alpha_t + gamma * (alpha - err_t)``, then clamp what is emitted.

    ``err`` is the realized miscoverage of the day just settled, in ``[0, 1]`` rather
    than the paper's ``{0, 1}``: 24 hourly outcomes arrive together at day-ahead, so one
    update per delivery day is the honest information arrival. Lemma 4.1 and
    Proposition 4.1 both survive that (the spec records the re-derivation); the property
    tests gate them on adversarial sequences rather than assuming it.
    """
    if not 0.0 <= err <= 1.0:
        raise ValueError(f"err must be a miscoverage rate in [0, 1]; got {err}")
    if state.gamma < 0.0:
        raise ValueError(f"gamma must be >= 0; got {state.gamma}")

    alpha = state.alpha + state.gamma * (state.alpha_target - err)
    lo, hi = state.clamp
    emitted = min(max(alpha, lo), hi)
    return replace(
        state,
        alpha=alpha,
        alpha_emitted=emitted,
        n_updates=state.n_updates + 1,
        n_clamped=state.n_clamped + (1 if emitted != alpha else 0),
    )


def aci_bound(*, alpha_1: float, gamma: float, n_updates: int) -> float:
    """Proposition 4.1's right-hand side: ``(max{a1, 1-a1} + gamma) / (gamma * T)``.

    The ``gamma`` in the denominator is what makes the bound vacuous on a short run and
    informative on a multi-year one, which is why the ACI gate scores a sequential run
    rather than a 5-day block. ``gamma = 0`` is the non-adaptive arm: the recursion never
    moves, so there is no long-run claim and the bound is infinite.
    """
    if n_updates < 1:
        raise ValueError(f"n_updates must be >= 1; got {n_updates}")
    if gamma < 0.0:
        raise ValueError(f"gamma must be >= 0; got {gamma}")
    if gamma == 0.0:
        return math.inf
    return float((max(alpha_1, 1.0 - alpha_1) + gamma) / (gamma * n_updates))


def aci_realized_gap(*, alpha_1: float, alpha_final: float, gamma: float, n_updates: int) -> float:
    """The exact miscoverage gap ``|mean(err) - alpha|``, read off the iterate.

    Expanding the recursion telescopes to
    ``alpha_{T+1} = alpha_1 + gamma * sum_t (alpha - err_t)``, so

        ``|mean(err) - alpha| == |alpha_{T+1} - alpha_1| / (gamma * T)``

    exactly, for any sequence whatsoever. Proposition 4.1 is this identity plus Lemma
    4.1's a-priori bound on ``|alpha_{T+1} - alpha_1|``, and **Lemma 4.1 needs the
    saturation feedback that clamping removes**: with the emitted level pinned inside
    ``clamp``, a level above 1 no longer forces a miss, so the unclamped iterate can run
    away and the a-priori bound stops applying.

    The identity does not care. It holds through any clamping, so it is what the
    sequential gate reads: a run whose iterate wandered far reports a correspondingly
    large gap, in place of a bound that quietly stopped being true.
    """
    if n_updates < 1:
        raise ValueError(f"n_updates must be >= 1; got {n_updates}")
    if gamma <= 0.0:
        raise ValueError(f"gamma must be > 0 to read a gap off the iterate; got {gamma}")
    return float(abs(alpha_final - alpha_1) / (gamma * n_updates))
