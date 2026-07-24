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


def gpd_quantile(p: float | np.ndarray, *, xi: float, beta: float | np.ndarray) -> np.ndarray:
    """GPD inverse CDF (excess magnitude) at probability ``p ∈ [0, 1)``.

    ``y(p) = (β/ξ)[(1−p)^(−ξ) − 1]`` for ξ ≠ 0, and ``−β·ln(1−p)`` for ξ = 0
    (the exponential limit). Vectorized over ``p``; ``beta`` may be a scalar or a
    per-element array (the R2.2c conditional scale, one β per exceedance).
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


def log_scale_slope(excess: np.ndarray, z: np.ndarray) -> float:
    """OLS slope of ``log(excess)`` on the standardized covariate ``z`` (raw, unclamped).

    The conditional GPD scale link is ``β(x) = β₀·exp(γ z)``; since ``log(excess)`` is
    ``log β(x)`` plus a covariate-free noise term, its OLS slope on ``z`` is an
    unbiased estimate of ``γ``. Returns 0.0 for a degenerate (zero-variance) ``z``.
    """
    z = np.asarray(z, dtype=float)
    log_excess = np.log(np.asarray(excess, dtype=float))
    zc = z - z.mean()
    denom = float(np.sum(zc * zc))
    if denom == 0.0:
        return 0.0
    return float(np.sum(zc * (log_excess - log_excess.mean())) / denom)


@dataclass(frozen=True)
class ConditionalTailModel:
    """A residual-load-conditional GPD tail (R2.2c): the scale rises with a covariate.

    The GPD shape ``ξ`` and the base scale ``β₀`` are R2.2b's unconditional PWM fit
    (``β₀`` is the scale at the average covariate, ``z = 0``); a log-link tilts the
    scale with the standardized covariate, ``β(x) = β₀·exp(γ·(x − x_mean)/x_std)``, so
    spikes are heavier on high-residual-load (tight-margin) hours. ``γ`` is fit by OLS
    of ``log(excess)`` on ``z`` and clamped ``≥ 0``. ``γ = 0`` is exactly R2.2b.
    """

    xi: float
    beta0: float
    gamma: float
    threshold: float
    side: str
    x_mean: float
    x_std: float

    @classmethod
    def fit(
        cls,
        residuals: np.ndarray,
        covariate: np.ndarray,
        *,
        threshold_quantile: float = 0.95,
        side: str = "upper",
    ) -> ConditionalTailModel:
        """Fit ξ/β₀ (PWM, unconditional) and the log-link scale slope γ (OLS, γ≥0).

        ``covariate`` is the residual load aligned element-for-element with
        ``residuals`` (both pooled/flattened). Standardization uses the whole
        covariate so the target covariate maps on the same scale at generation.
        """
        if side not in ("upper", "lower"):
            raise ValueError(f"side must be 'upper' or 'lower'; got {side!r}")
        r = np.asarray(residuals, dtype=float).ravel()
        x = np.asarray(covariate, dtype=float).ravel()
        if x.shape != r.shape:
            raise ValueError("covariate must align element-for-element with residuals")
        x_mean = float(x.mean())
        x_std = float(x.std())
        if x_std == 0.0:
            raise ValueError("covariate is constant; cannot condition the tail on it")

        if side == "upper":
            u = float(np.quantile(r, threshold_quantile))
            mask = r > u
            excess = r[mask] - u
        else:
            u = float(np.quantile(r, 1.0 - threshold_quantile))
            mask = r < u
            excess = u - r[mask]
        xi, beta0 = fit_gpd_pwm(excess)

        z = (x[mask] - x_mean) / x_std
        gamma = max(
            0.0, log_scale_slope(excess, z)
        )  # a spike tail must not get lighter on tight hours
        return cls(
            xi=xi, beta0=beta0, gamma=gamma, threshold=u, side=side, x_mean=x_mean, x_std=x_std
        )

    def beta_at(self, x: np.ndarray) -> np.ndarray:
        """The conditional scale ``β(x) = β₀·exp(γ·(x − x_mean)/x_std)``."""
        z = (np.asarray(x, dtype=float) - self.x_mean) / self.x_std
        return self.beta0 * np.exp(self.gamma * z)


def apply_tail(
    resid_draws: np.ndarray,
    tail: TailModel | ConditionalTailModel,
    rng: np.random.Generator,
    *,
    covariate: np.ndarray | None = None,
) -> np.ndarray:
    """Splice residual exceedances over the tail threshold with fresh GPD draws.

    Returns a copy of ``resid_draws`` (shape ``(n, T)``) in which every component
    beyond the threshold (above it for an upper tail, below for a lower tail) has its
    *excess over the threshold* replaced by a GPD-sampled excess. The exceedance
    *frequency* stays empirical (it is whatever the bootstrap drew); only the
    *magnitude* becomes parametric, so the tail can exceed the historical maximum.

    For a :class:`ConditionalTailModel` (R2.2c) the GPD scale is per-hour, from the
    target ``covariate`` (length ``T``): a spliced exceedance in hour ``t`` draws from
    ``GPD(ξ, β(covariate[t]))``, so tighter hours spike larger.
    """
    out = np.array(resid_draws, dtype=float, copy=True)
    mask = out > tail.threshold if tail.side == "upper" else out < tail.threshold
    k = int(mask.sum())
    if k == 0:
        return out

    u = rng.random(k)
    if isinstance(tail, ConditionalTailModel):
        if covariate is None or len(covariate) != out.shape[1]:
            raise ValueError("conditional tail needs a per-hour covariate of length T")
        beta_per_hour = tail.beta_at(np.asarray(covariate, dtype=float))
        cols = np.nonzero(mask)[1]  # the hour index of each exceedance, row-major to match u
        excess = gpd_quantile(u, xi=tail.xi, beta=beta_per_hour[cols])
    else:
        excess = gpd_quantile(u, xi=tail.xi, beta=tail.beta)

    if tail.side == "upper":
        out[mask] = tail.threshold + excess
    else:
        out[mask] = tail.threshold - excess
    return out
