"""Property invariants for the R2.2b peaks-over-threshold scenario tail.

Pure numpy/pandas (main CI job, no forecast group). The load-bearing invariants:
the tail is opt-in (off ⇒ exactly R2.2), touches only exceedances, and *un-caps*
the bootstrap (a path can exceed the historical-maximum residual, which the plain
bootstrap cannot). Spec: ``docs/specs/R2.2b-spike-tail.md``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bess.scenarios import generate_scenarios, reduce_scenarios
from bess.scenarios.tail import TailModel, fit_gpd_pwm, gpd_quantile


class _FakeForecast:
    def __init__(self, point: np.ndarray, index: pd.DatetimeIndex) -> None:
        self.point = pd.Series(point, index=index, name="point")


def _forecast(t: int, level: float = 50.0) -> _FakeForecast:
    idx = pd.date_range("2026-01-01", periods=t, freq="h", tz="UTC")
    return _FakeForecast(np.full(t, level), idx)


def _residuals(rng: np.random.Generator, m: int, t: int) -> np.ndarray:
    return rng.normal(0.0, 10.0, size=(m, t))


# ------------------------------- fit / quantile -------------------------------


def test_pwm_exponential_case_is_zero_shape_scale_mean():
    # Exact-ish: for excesses from an exponential the PWM shape ~ 0 and scale ~ mean.
    rng = np.random.default_rng(0)
    excess = rng.exponential(3.0, size=20000)
    xi, beta = fit_gpd_pwm(excess)
    assert abs(xi) < 0.05
    assert abs(beta - excess.mean()) < 0.1


@settings(max_examples=50, deadline=None)
@given(
    p=st.floats(0.0, 0.999),
    xi=st.floats(-0.9, 0.9),
    beta=st.floats(0.1, 20.0),
)
def test_gpd_quantile_nonnegative_and_monotone(p: float, xi: float, beta: float):
    y = gpd_quantile(p, xi=xi, beta=beta)
    assert y >= -1e-9  # excesses are non-negative
    assert (
        gpd_quantile(p, xi=xi, beta=beta)
        <= gpd_quantile(min(p + 0.05, 0.999), xi=xi, beta=beta) + 1e-9
    )


# --------------------------------- generation ---------------------------------


def test_opt_in_identity_across_seeds():
    for seed in range(5):
        rng = np.random.default_rng(seed)
        resid = _residuals(rng, 15, 4)
        fc = _forecast(4)
        a = generate_scenarios(fc, resid, n=30, seed=seed)
        b = generate_scenarios(fc, resid, n=30, seed=seed, tail=None)
        np.testing.assert_array_equal(a.paths, b.paths)


@settings(max_examples=30, deadline=None)
@given(seed=st.integers(0, 2**16))
def test_body_preserved_only_exceedances_change(seed: int):
    rng = np.random.default_rng(seed)
    resid = _residuals(rng, 20, 5)
    fc = _forecast(5)
    plain = generate_scenarios(fc, resid, n=40, seed=seed)
    tail = TailModel.fit(resid, threshold_quantile=0.9, side="upper")
    spliced = generate_scenarios(fc, resid, n=40, seed=seed, tail=tail)

    plain_resid = plain.paths - 50.0
    spliced_resid = spliced.paths - 50.0
    below = plain_resid <= tail.threshold
    np.testing.assert_array_equal(spliced_resid[below], plain_resid[below])


def test_un_caps_the_bootstrap():
    # A heavy tail (ξ>0) must let a scenario exceed the historical-max residual,
    # which the plain bootstrap can never do.
    rng = np.random.default_rng(3)
    resid = _residuals(rng, 60, 6)
    fc = _forecast(6)
    hist_max = resid.max()

    plain = generate_scenarios(fc, resid, n=4000, seed=5)
    assert (plain.paths - 50.0).max() <= hist_max + 1e-9  # capped by construction

    tail = TailModel(
        xi=0.4, beta=float(np.std(resid)), threshold=float(hist_max * 0.8), side="upper"
    )
    spliced = generate_scenarios(fc, resid, n=4000, seed=5, tail=tail)
    assert (spliced.paths - 50.0).max() > hist_max  # tail exceeds history


def test_heavier_tail_gives_larger_expected_maximum():
    rng = np.random.default_rng(1)
    resid = _residuals(rng, 40, 6)
    fc = _forecast(6)
    u = float(np.quantile(resid, 0.9))
    light = TailModel(xi=0.1, beta=5.0, threshold=u, side="upper")
    heavy = TailModel(xi=0.1, beta=20.0, threshold=u, side="upper")
    m_light = (generate_scenarios(fc, resid, n=3000, seed=2, tail=light).paths).max()
    m_heavy = (generate_scenarios(fc, resid, n=3000, seed=2, tail=heavy).paths).max()
    assert m_heavy > m_light


def test_valid_measure_and_count_unchanged():
    rng = np.random.default_rng(9)
    resid = _residuals(rng, 25, 4)
    fc = _forecast(4)
    tail = TailModel.fit(resid, threshold_quantile=0.9, side="upper")
    s = generate_scenarios(fc, resid, n=50, seed=4, tail=tail)
    assert s.n_scenarios == 50
    assert np.isclose(s.probs.sum(), 1.0)
    assert (s.probs >= 0).all()


def test_determinism():
    rng = np.random.default_rng(0)
    resid = _residuals(rng, 20, 5)
    fc = _forecast(5)
    tail = TailModel.fit(resid, threshold_quantile=0.9, side="upper")
    a = generate_scenarios(fc, resid, n=100, seed=11, tail=tail)
    b = generate_scenarios(fc, resid, n=100, seed=11, tail=tail)
    np.testing.assert_array_equal(a.paths, b.paths)


def test_reduction_retains_the_tail():
    """Open question 1, measured: forward-selection reduction keeps the spike paths.

    Extreme paths sit far from the mass, so dropping one incurs a large Kantorovich
    cost; the reducer therefore keeps them. Measured over seeds: the reduced set's
    maximum equals the full set's, and several reduced paths stay above the
    historical-max residual. So no tail quota is needed; this test guards that.
    """
    for seed in range(4):
        rng = np.random.default_rng(seed)
        resid = _residuals(rng, 60, 24)
        fc = _forecast(24)
        hist_max = resid.max()
        tail = TailModel(
            xi=0.3,
            beta=float(np.std(resid)),
            threshold=float(np.quantile(resid, 0.95)),
            side="upper",
        )
        full = generate_scenarios(fc, resid, n=300, seed=seed, tail=tail)
        reduced, _ = reduce_scenarios(full, n_reduced=50, method="forward")
        assert (reduced.paths - 50.0).max() > hist_max  # the tail survives reduction


def test_fit_rejects_too_few_exceedances():
    # A threshold so high there are < 2 exceedances cannot fit a 2-parameter GPD.
    resid = np.array([[1.0, 2.0, 3.0, 100.0]])
    with pytest.raises(ValueError):
        TailModel.fit(resid, threshold_quantile=0.999, side="upper")
