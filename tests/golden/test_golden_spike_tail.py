"""Golden oracles for the R2.2b peaks-over-threshold scenario tail.

The GPD fit (PWM) and the exceedance splice are exact arithmetic, so R2.2b gets
real golden oracles, not only statistical gates. Pinned by hand from the
Hosking-Wallis PWM formulas and the GPD inverse-CDF. Spec:
``docs/specs/R2.2b-spike-tail.md``. Pure numpy/pandas (no forecast group).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bess.scenarios import generate_scenarios
from bess.scenarios.tail import TailModel, fit_gpd_pwm, gpd_quantile


class _FakeForecast:
    def __init__(self, point: np.ndarray, index: pd.DatetimeIndex) -> None:
        self.point = pd.Series(point, index=index, name="point")


def _forecast(t: int) -> _FakeForecast:
    idx = pd.date_range("2026-01-01", periods=t, freq="h", tz="UTC")
    return _FakeForecast(np.full(t, 50.0), idx)


def test_oracle1_pwm_fit_matches_hand_computation():
    # excess = [1, 2, 3]: a0 = 2, a1 = (1/3)(1·1 + 0.5·2 + 0·3) = 2/3,
    # denom = a0 − 2a1 = 2/3, ξ = 2 − a0/denom = 2 − 3 = −1, β = 2·a0·a1/denom = 4.
    xi, beta = fit_gpd_pwm(np.array([1.0, 2.0, 3.0]))
    assert xi == pytest.approx(-1.0, abs=1e-12)
    assert beta == pytest.approx(4.0, abs=1e-12)


def test_oracle2_gpd_quantile_exact():
    # ξ=−1, β=4 ⇒ y(p) = (β/ξ)[(1−p)^{−ξ} − 1] = −4[(1−p) − 1] = 4p (linear).
    assert gpd_quantile(0.0, xi=-1.0, beta=4.0) == 0.0
    assert gpd_quantile(0.25, xi=-1.0, beta=4.0) == 1.0
    assert gpd_quantile(0.5, xi=-1.0, beta=4.0) == 2.0
    # ξ=0 (exponential): y(p) = −β ln(1−p); y(0) = 0.
    assert gpd_quantile(0.0, xi=0.0, beta=3.0) == 0.0


def test_oracle3_opt_in_identity_tail_none_equals_r22():
    fc = _forecast(4)
    resid = np.array([[1.0, -2.0, 3.0, 0.0], [5.0, 1.0, -1.0, 2.0], [0.0, 0.0, 4.0, -3.0]])
    base = generate_scenarios(fc, resid, n=20, seed=7)
    with_none = generate_scenarios(fc, resid, n=20, seed=7, tail=None)
    np.testing.assert_array_equal(base.paths, with_none.paths)
    np.testing.assert_array_equal(base.probs, with_none.probs)


def test_oracle4_threshold_above_all_residuals_is_identity():
    fc = _forecast(4)
    resid = np.array([[1.0, -2.0, 3.0, 0.0], [5.0, 1.0, -1.0, 2.0], [0.0, 0.0, 4.0, -3.0]])
    base = generate_scenarios(fc, resid, n=20, seed=7)
    # No residual component exceeds the threshold ⇒ no exceedance to splice.
    huge = TailModel(xi=0.2, beta=1.0, threshold=1e9, side="upper")
    spliced = generate_scenarios(fc, resid, n=20, seed=7, tail=huge)
    np.testing.assert_array_equal(base.paths, spliced.paths)


def test_oracle5_splice_touches_only_exceedances():
    fc = _forecast(3)
    # One clearly-extreme component (100) sits above the threshold; the rest below.
    resid = np.array([[1.0, 2.0, 100.0], [0.0, 1.0, 3.0], [2.0, -1.0, 4.0]])
    plain = generate_scenarios(fc, resid, n=50, seed=1)
    tail = TailModel(xi=0.1, beta=5.0, threshold=50.0, side="upper")
    spliced = generate_scenarios(fc, resid, n=50, seed=1, tail=tail)

    # Positions where the plain residual was <= threshold are untouched;
    # positions above the threshold are replaced (and stay above it).
    plain_resid = plain.paths - 50.0
    spliced_resid = spliced.paths - 50.0
    above = plain_resid > 50.0
    np.testing.assert_array_equal(spliced_resid[~above], plain_resid[~above])
    assert np.all(spliced_resid[above] > 50.0)
