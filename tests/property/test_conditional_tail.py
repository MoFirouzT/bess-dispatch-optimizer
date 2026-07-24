"""Property invariants for the R2.2c residual-load-conditional scenario tail.

Pure numpy/pandas (main CI job). Load-bearing invariants: γ=0 is exactly R2.2b;
the spike magnitude is monotone in the covariate; γ is clamped non-negative; and a
covariate carrying no signal fits γ≈0 (reduces to R2.2b). Spec:
``docs/specs/R2.2c-conditional-tail.md``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from bess.scenarios import generate_scenarios
from bess.scenarios.tail import ConditionalTailModel, TailModel


class _FakeForecast:
    def __init__(self, point: np.ndarray, index: pd.DatetimeIndex) -> None:
        self.point = pd.Series(point, index=index, name="point")


def _forecast(t: int) -> _FakeForecast:
    idx = pd.date_range("2026-01-01", periods=t, freq="h", tz="UTC")
    return _FakeForecast(np.full(t, 50.0), idx)


def _residuals(rng: np.random.Generator, m: int, t: int) -> np.ndarray:
    return rng.normal(0.0, 10.0, size=(m, t))


def test_opt_in_identity_gamma_zero_equals_r22b():
    for seed in range(4):
        rng = np.random.default_rng(seed)
        resid = _residuals(rng, 20, 5)
        fc = _forecast(5)
        base = TailModel.fit(resid, threshold_quantile=0.9, side="upper")
        cond = ConditionalTailModel(
            xi=base.xi,
            beta0=base.beta,
            gamma=0.0,
            threshold=base.threshold,
            side="upper",
            x_mean=0.0,
            x_std=1.0,
        )
        cov = rng.normal(100.0, 30.0, size=5)
        a = generate_scenarios(fc, resid, n=40, seed=seed, tail=base)
        b = generate_scenarios(fc, resid, n=40, seed=seed, tail=cond, tail_covariate=cov)
        np.testing.assert_array_equal(a.paths, b.paths)


def test_spike_magnitude_monotone_in_covariate():
    """Two hours, identical except the covariate: the high-residual-load hour spikes larger."""
    rng = np.random.default_rng(1)
    resid = _residuals(rng, 40, 2)
    resid[:, :] = np.abs(resid) + 60.0  # force both hours to exceed the threshold every draw
    fc = _forecast(2)
    model = ConditionalTailModel(
        xi=0.2, beta0=8.0, gamma=0.8, threshold=50.0, side="upper", x_mean=100.0, x_std=40.0
    )
    cov = np.array([60.0, 160.0])  # hour 0 slack, hour 1 tight
    s = generate_scenarios(fc, resid, n=6000, seed=0, tail=model, tail_covariate=cov)
    resid_out = s.paths - 50.0
    assert resid_out[:, 1].mean() > resid_out[:, 0].mean()  # tighter hour, larger spikes


def test_gamma_clamped_non_negative():
    rng = np.random.default_rng(2)
    cov = np.linspace(0.0, 10.0, 60)
    z = (cov - cov.mean()) / cov.std()
    excess = np.exp(-1.5 * z) * rng.uniform(0.8, 1.2, 60)  # decreasing in z
    resid = (excess).reshape(1, -1)
    model = ConditionalTailModel.fit(resid, cov.reshape(1, -1), threshold_quantile=0.0001)
    assert model.gamma >= 0.0


def test_no_signal_covariate_fits_gamma_near_zero():
    rng = np.random.default_rng(5)
    resid = np.abs(rng.normal(0, 10, size=(80, 6))) + 5.0
    cov = rng.normal(100.0, 30.0, size=(80, 6))  # independent of the residuals
    model = ConditionalTailModel.fit(resid, cov, threshold_quantile=0.9, side="upper")
    assert abs(model.gamma) < 0.5  # no covariate signal ⇒ near-flat scale


@settings(max_examples=20, deadline=None)
@given(seed=st.integers(0, 2**16))
def test_determinism(seed: int):
    rng = np.random.default_rng(seed)
    resid = _residuals(rng, 20, 5)
    fc = _forecast(5)
    cov = rng.normal(100.0, 30.0, size=5)
    model = ConditionalTailModel(
        xi=0.15,
        beta0=7.0,
        gamma=0.3,
        threshold=float(np.quantile(resid, 0.9)),
        side="upper",
        x_mean=100.0,
        x_std=30.0,
    )
    a = generate_scenarios(fc, resid, n=50, seed=11, tail=model, tail_covariate=cov)
    b = generate_scenarios(fc, resid, n=50, seed=11, tail=model, tail_covariate=cov)
    np.testing.assert_array_equal(a.paths, b.paths)
