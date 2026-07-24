"""Peaks-over-threshold (GPD) tail for the scenario bootstrap (R2.2b).

Spec: ``docs/specs/R2.2b-spike-tail.md``; theory + references: ``references.md`` §R2.2b
(Coles 2001 ch. 4; PWM estimator from Hosking & Wallis 1987). No ``formulation.md``
section (a statistical scenario-layer extension, classified with R2.1b).

The R2.2 residual-path bootstrap can only replay historical forecast errors, so the
worst spike any scenario contains is capped at the historical-maximum residual. This
module fits a **Generalized Pareto Distribution** to the residual *exceedances over a
high threshold* and splices those exceedances with GPD draws, giving a semiparametric
generator: empirical body (unchanged), extreme-value tail (un-capped). The fit is
probability-weighted moments (closed form), so it is pure-numpy and deterministic.

Pure numpy: no ``scipy``, no optional group.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def fit_gpd_pwm(excess: np.ndarray) -> tuple[float, float]:
    """Probability-weighted-moments fit of a GPD to non-negative ``excess`` values.

    Returns ``(xi, beta)`` (shape ξ, scale β) for the excess distribution
    ``H(y) = 1 − (1 + ξ y/β)^(−1/ξ)``. Hosking & Wallis (1987): with the ascending
    order statistics ``y₍₁₎ ≤ … ≤ y₍ₙ₎``,

        a0 = mean(y),  a1 = (1/n) Σᵢ ((n−i)/(n−1)) y₍ᵢ₎,
        ξ = 2 − a0/(a0 − 2 a1),   β = 2 a0 a1 / (a0 − 2 a1).

    Needs at least two exceedances (a two-parameter fit).
    """
    y = np.sort(np.asarray(excess, dtype=float))
    n = y.size
    if n < 2:
        raise ValueError(f"GPD fit needs >= 2 exceedances; got {n}")
    i = np.arange(1, n + 1)
    a0 = float(y.mean())
    a1 = float(np.mean((n - i) / (n - 1) * y))
    denom = a0 - 2.0 * a1
    if denom == 0.0:
        raise ValueError("degenerate PWM fit (a0 == 2·a1); exceedances carry no scale")
    xi = 2.0 - a0 / denom
    beta = 2.0 * a0 * a1 / denom
    return xi, beta


def gpd_quantile(p: float | np.ndarray, *, xi: float, beta: float) -> np.ndarray:
    """GPD inverse CDF (excess magnitude) at probability ``p ∈ [0, 1)``.

    ``y(p) = (β/ξ)[(1−p)^(−ξ) − 1]`` for ξ ≠ 0, and ``−β·ln(1−p)`` for ξ = 0
    (the exponential limit). Vectorized over ``p``.
    """
    q = np.asarray(p, dtype=float)
    one_minus = 1.0 - q
    if abs(xi) < 1e-12:
        return -beta * np.log(one_minus)
    return (beta / xi) * (one_minus ** (-xi) - 1.0)


@dataclass(frozen=True)
class TailModel:
    """A fitted GPD tail for the scenario bootstrap (peaks-over-threshold)."""

    xi: float  # GPD shape ξ
    beta: float  # GPD scale β (> 0)
    threshold: float  # POT threshold u, in residual units (€/MWh)
    side: str  # "upper" (price-spike tail) | "lower" (negative-price tail)

    @classmethod
    def fit(
        cls,
        residuals: np.ndarray,
        *,
        threshold_quantile: float = 0.95,
        side: str = "upper",
    ) -> TailModel:
        """Fit a GPD to the residual exceedances over the quantile threshold.

        ``residuals`` may be the ``(M, T)`` whole-day residual matrix or any array;
        it is pooled (flattened). For ``side="upper"`` the threshold is the
        ``threshold_quantile`` quantile and the excesses are ``r − u`` over it; for
        ``"lower"`` it mirrors below the ``1 − threshold_quantile`` quantile.
        """
        if side not in ("upper", "lower"):
            raise ValueError(f"side must be 'upper' or 'lower'; got {side!r}")
        if not 0.0 < threshold_quantile < 1.0:
            raise ValueError("threshold_quantile must be in (0, 1)")
        r = np.asarray(residuals, dtype=float).ravel()
        if side == "upper":
            u = float(np.quantile(r, threshold_quantile))
            excess = r[r > u] - u
        else:
            u = float(np.quantile(r, 1.0 - threshold_quantile))
            excess = u - r[r < u]
        xi, beta = fit_gpd_pwm(excess)
        return cls(xi=xi, beta=beta, threshold=u, side=side)


def apply_tail(resid_draws: np.ndarray, tail: TailModel, rng: np.random.Generator) -> np.ndarray:
    """Splice residual exceedances over the tail threshold with fresh GPD draws.

    Returns a copy of ``resid_draws`` (shape ``(n, T)``) in which every component
    beyond the threshold (above it for an upper tail, below for a lower tail) has its
    *excess over the threshold* replaced by a GPD-sampled excess. The exceedance
    *frequency* stays empirical (it is whatever the bootstrap drew); only the
    *magnitude* becomes parametric, so the tail can exceed the historical maximum.
    """
    out = np.array(resid_draws, dtype=float, copy=True)
    mask = out > tail.threshold if tail.side == "upper" else out < tail.threshold
    k = int(mask.sum())
    if k == 0:
        return out
    excess = gpd_quantile(rng.random(k), xi=tail.xi, beta=tail.beta)
    if tail.side == "upper":
        out[mask] = tail.threshold + excess
    else:
        out[mask] = tail.threshold - excess
    return out
