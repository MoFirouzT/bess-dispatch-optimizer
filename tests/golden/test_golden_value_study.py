"""Golden oracles for R2.5: value evaluation hardening (formulation §R2.5).

Contract: docs/specs/R2.5-value-evaluation.md § "Golden oracles".

Exact, hand-computable cases for the pinball loss and the seasonal-naive
predictor; designed-instance cases for the per-window VSS study (the window
machinery must reproduce the R2.3 out-of-sample result and add no value of its
own) and the forecast-value comparison (null when its inputs are identical).
All token-free and forecast-group-free: the ML wrapper is exercised by the
live integration tests, the value arithmetic here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bess.assets.battery import BatterySpec
from bess.forecaster.evaluate import pinball_loss, seasonal_naive
from bess.stochastic.study import (
    forecast_value_from_sets,
    vss_across_windows,
    window_sets,
)
from bess.stochastic.vss import out_of_sample_vss

TOL = 1e-6

# Same battery as the R2.3 designed-instance gate: headroom at both ends
# (capacity 2, anchored half-full) so the commitment has real freedom.
_BATT = BatterySpec(capacity=2.0, soc_initial=0.5, soc_terminal=0.5)


# ------------------------------------------------------------- pinball loss


def test_oracle_1_pinball_exact() -> None:
    """y=[10,20,30], q̂=[12,18,30], τ=0.9 — by hand.

    d = y − q̂ = [−2, 2, 0]; per-point loss max{τd, (τ−1)d} = [0.2, 1.8, 0.0];
    mean = 2/3. Pins the max form and the τ asymmetry (under-prediction of a
    high quantile costs τ per unit, over-prediction only 1−τ).
    """
    loss = pinball_loss([10.0, 20.0, 30.0], [12.0, 18.0, 30.0], tau=0.9)
    assert loss == pytest.approx(2.0 / 3.0, abs=TOL)


def test_oracle_2_pinball_median_is_half_mae() -> None:
    """At τ=0.5 the pinball loss equals MAE/2 exactly (quantile-loss identity)."""
    y = np.array([10.0, 20.0, 30.0, -5.0])
    q = np.array([12.0, 18.0, 30.0, 5.0])
    mae = float(np.mean(np.abs(y - q)))
    assert pinball_loss(y, q, tau=0.5) == pytest.approx(mae / 2.0, abs=TOL)


# ---------------------------------------------------------- seasonal naive


def test_oracle_3_seasonal_naive_lag_and_fallback() -> None:
    """14 hourly days, values encoding (day, hour): the prediction at t is the
    actual at t − 7 days once a week of history exists, the actual at t − 1 day
    before that (the short-history fallback), and absent on the first day."""
    idx = pd.date_range("2024-01-01", periods=14 * 24, freq="h", tz="UTC")
    prices = pd.Series([100.0 * (i // 24) + (i % 24) for i in range(len(idx))], index=idx)

    naive = seasonal_naive(prices, lag_days=7)

    # Day 0 has neither lag: absent.
    assert naive.index.min() == idx[24]
    assert len(naive) == 13 * 24
    # Days 1–6: 1-day fallback.
    t = pd.Timestamp("2024-01-03 05:00", tz="UTC")
    assert naive[t] == prices[t - pd.Timedelta(days=1)]
    # Day 7 onward: the true 7-day seasonal lag.
    t = pd.Timestamp("2024-01-12 17:00", tz="UTC")
    assert naive[t] == prices[t - pd.Timedelta(days=7)]


# ------------------------------------------- per-window out-of-sample VSS


def _designed_day(rng: np.random.Generator) -> np.ndarray:
    """A 24 h day with the R2.3 value-generating structure: a common cheap
    charge hour (t0) and a peak at a *random* early hour, flat elsewhere."""
    p = rng.uniform(8.0, 12.0, size=24)
    p[0] = rng.uniform(3.0, 6.0)
    p[rng.integers(1, 4)] = rng.uniform(45.0, 60.0)
    return p


def _series_from_days(days: np.ndarray, start: str = "2024-03-01") -> pd.Series:
    idx = pd.date_range(start, periods=days.size, freq="h", tz="UTC")
    return pd.Series(days.ravel(), index=idx)


def test_oracle_4_designed_window_reproduces_r23_vss() -> None:
    """On a series whose days all carry the R2.3 designed structure, the single
    study window must (a) report a strictly positive out-of-sample VSS (the
    R2.3 escape, now reached through the window machinery) and (b) agree
    exactly with a direct `out_of_sample_vss` call on the same sets — the
    distribution machinery adds no value of its own."""
    rng = np.random.default_rng(7)
    days = np.asarray([_designed_day(rng) for _ in range(13)])
    prices = _series_from_days(days)

    kwargs = dict(history_days=12, n_scenarios=16, seed=0)
    results = vss_across_windows(prices, _BATT, rho=0.4, **kwargs)

    assert len(results) == 1
    w = results[0]
    assert w.window_start == pd.Timestamp("2024-03-13", tz="UTC")
    assert w.vss_oos == pytest.approx(w.rp_oos - w.eev_oos, abs=TOL)
    assert w.vss_oos > 1e-3  # the designed instance generalises, as in R2.3

    ((ws, train, evaluation),) = window_sets(prices, **kwargs)
    direct = out_of_sample_vss(train, evaluation, _BATT, rho=0.4)
    assert ws == w.window_start
    assert w.rp_oos == pytest.approx(direct.rp_oos, abs=TOL)
    assert w.eev_oos == pytest.approx(direct.eev_oos, abs=TOL)


def test_oracle_4b_identical_days_give_zero_vss() -> None:
    """Every history day identical to the realized day ⇒ the stochastic and
    mean-value commitments face the same (degenerate) distribution and score
    identically on the realized path: VSS = 0, with non-trivial profits (the
    day has real spread, so zero comes from degeneracy, not from idleness)."""
    day = np.full(24, 10.0)
    day[0], day[6] = 3.0, 50.0
    prices = _series_from_days(np.tile(day, (13, 1)))

    results = vss_across_windows(prices, _BATT, history_days=12, n_scenarios=16, rho=0.4, seed=0)

    assert len(results) == 1
    w = results[0]
    assert w.rp_oos > 1.0  # the day is genuinely profitable
    assert w.vss_oos == pytest.approx(0.0, abs=1e-5)


# ---------------------------------------------------------- forecast value


def test_oracle_6_fv_windows_loop_adds_no_value() -> None:
    """`fv_windows_from_sets` bookkeeping (R2.5 amendment 2026-07-22): identical
    set pairs give exactly zero FV per window, window starts pass through in
    order, and the loop equals per-item `forecast_value_from_sets` calls — the
    distribution machinery adds no value of its own."""
    from bess.scenarios import ScenarioSet
    from bess.stochastic.study import fv_windows_from_sets

    rng = np.random.default_rng(3)
    idx = pd.date_range("2024-03-01", periods=24, freq="h", tz="UTC")

    def scen(seed: int) -> ScenarioSet:
        r = np.random.default_rng(seed)
        return ScenarioSet(
            paths=np.asarray([_designed_day(r) for _ in range(5)]),
            probs=np.full(5, 0.2),
            index=idx,
        )

    a, b = scen(10), scen(11)
    realized = rng.uniform(0.0, 60.0, 24)
    starts = [pd.Timestamp("2024-03-10", tz="UTC"), pd.Timestamp("2024-03-11", tz="UTC")]
    items = [(starts[0], a, a, realized), (starts[1], a, b, realized)]

    windows = fv_windows_from_sets(items, _BATT, rho=0.4)

    assert [w.window_start for w in windows] == starts
    # Identical pair: exactly null.
    assert windows[0].fv_eur == pytest.approx(0.0, abs=1e-9)
    # Distinct pair: equals the single-item scoring, component by component.
    direct = forecast_value_from_sets(a, b, realized, _BATT, rho=0.4)
    assert windows[1].profit_conformal_eur == pytest.approx(direct.profit_conformal_eur, abs=1e-9)
    assert windows[1].profit_naive_eur == pytest.approx(direct.profit_naive_eur, abs=1e-9)
    assert windows[1].fv_eur == pytest.approx(direct.fv_eur, abs=1e-9)


def test_oracle_5_forecast_value_null_on_identical_sets() -> None:
    """With identical scenario sets on both sides the comparison is exactly
    null: same commitment, same score, FV = 0."""
    rng = np.random.default_rng(1)
    days = np.asarray([_designed_day(rng) for _ in range(8)])
    idx = pd.date_range("2024-03-01", periods=24, freq="h", tz="UTC")
    from bess.scenarios import ScenarioSet

    scen = ScenarioSet(paths=days, probs=np.full(8, 1 / 8), index=idx)
    realized = days[0]

    fv = forecast_value_from_sets(scen, scen, realized, _BATT, rho=0.4)
    assert fv.profit_conformal_eur == pytest.approx(fv.profit_naive_eur, abs=1e-9)
    assert fv.fv_eur == pytest.approx(0.0, abs=1e-9)
