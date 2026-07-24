"""Golden oracles for the R2.2c residual-load-conditional scenario tail.

The conditional-scale fit (OLS log-link slope on the standardized covariate, base
scale from R2.2b's PWM) and the per-hour splice are exact arithmetic. Spec:
``docs/specs/R2.2c-conditional-tail.md``. Pure numpy/pandas (no forecast group).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bess.scenarios import generate_scenarios
from bess.scenarios.tail import ConditionalTailModel, TailModel, log_scale_slope


class _FakeForecast:
    def __init__(self, point: np.ndarray, index: pd.DatetimeIndex) -> None:
        self.point = pd.Series(point, index=index, name="point")


def _forecast(t: int) -> _FakeForecast:
    idx = pd.date_range("2026-01-01", periods=t, freq="h", tz="UTC")
    return _FakeForecast(np.full(t, 50.0), idx)


def test_oracle1_gamma_zero_is_identical_to_r22b():
    """A conditional model with γ=0 splices exactly like the R2.2b unconditional tail."""
    fc = _forecast(4)
    resid = np.array([[1.0, -2.0, 60.0, 0.0], [80.0, 1.0, -1.0, 2.0], [0.0, 0.0, 70.0, -3.0]])
    threshold, xi, beta = 40.0, 0.2, 6.0

    uncond = TailModel(xi=xi, beta=beta, threshold=threshold, side="upper")
    cond = ConditionalTailModel(
        xi=xi, beta0=beta, gamma=0.0, threshold=threshold, side="upper", x_mean=0.0, x_std=1.0
    )
    cov = np.array([100.0, 200.0, 300.0, 400.0])  # any covariate: γ=0 ignores it

    a = generate_scenarios(fc, resid, n=30, seed=3, tail=uncond)
    b = generate_scenarios(fc, resid, n=30, seed=3, tail=cond, tail_covariate=cov)
    np.testing.assert_array_equal(a.paths, b.paths)


def test_oracle2_ols_slope_exact():
    """log(excess) = z exactly ⇒ the OLS slope (γ estimate) is exactly 1."""
    z = np.array([-1.0, 0.0, 1.0])
    excess = np.exp(z)  # log(excess) == z
    assert log_scale_slope(excess, z) == pytest.approx(1.0, abs=1e-12)
    # A doubled slope: log(excess) = 2z ⇒ slope 2.
    assert log_scale_slope(np.exp(2.0 * z), z) == pytest.approx(2.0, abs=1e-12)
    # Degenerate z ⇒ 0 (no covariate variation).
    assert log_scale_slope(np.array([1.0, 2.0, 3.0]), np.array([4.0, 4.0, 4.0])) == 0.0


def test_oracle2b_base_scale_is_the_r22b_pwm_fit():
    """β₀ (the scale at z=0) equals R2.2b's unconditional PWM scale on the same excesses."""
    rng = np.random.default_rng(0)
    resid = np.abs(rng.normal(0, 10, size=(30, 6))) + 5.0
    cov = rng.normal(100.0, 30.0, size=(30, 6))
    cond = ConditionalTailModel.fit(resid, cov, threshold_quantile=0.9, side="upper")
    uncond = TailModel.fit(resid, threshold_quantile=0.9, side="upper")
    assert cond.beta0 == pytest.approx(uncond.beta, rel=1e-12)
    assert cond.xi == pytest.approx(uncond.xi, rel=1e-12)


def test_oracle3_beta_rises_with_the_covariate():
    """β(x) = β0·exp(γ·z) is monotone increasing in the covariate for γ>0."""
    model = ConditionalTailModel(
        xi=0.2, beta0=6.0, gamma=0.5, threshold=40.0, side="upper", x_mean=100.0, x_std=50.0
    )
    lo = model.beta_at(np.array([50.0]))[0]
    mid = model.beta_at(np.array([100.0]))[0]
    hi = model.beta_at(np.array([150.0]))[0]
    assert lo < mid < hi
    assert mid == pytest.approx(6.0)  # at x = x_mean, β = β0


def test_oracle4_negative_slope_is_clamped_to_zero():
    """A covariate that would give γ<0 (spikes lighter on tight hours) is clamped."""
    cov = np.linspace(5.0, 25.0, 40)
    z = (cov - cov.mean()) / cov.std()
    excess = np.exp(-z)  # decreasing in z ⇒ raw OLS slope < 0
    resid = (0.0 + excess).reshape(1, -1)
    cov2d = cov.reshape(1, -1)
    model = ConditionalTailModel.fit(resid, cov2d, threshold_quantile=0.0001, side="upper")
    assert model.gamma == 0.0
