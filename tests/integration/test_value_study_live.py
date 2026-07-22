"""Integration — R2.5 value evaluation on real ENTSO-E day-ahead prices.

Contract: docs/specs/R2.5-value-evaluation.md § "Statistical gates".
Token-gated: skipped unless `ENTSOE_API_TOKEN` is set (never runs in CI). Nothing
fetched here is committed — real prices are pulled at runtime and discarded.

What it proves on *real* prices:
  (a) over 4+ disjoint real weeks of windows, the median per-window out-of-sample
      VSS is >= 0 and every window's training set obeys the in-sample
      Birge-Louveaux ordering EEV <= RP <= WS;
  (b) the conformal forecaster has pinball *skill* over seasonal-naive at both
      interval edges (ratio < 1) under the leakage-safe walk-forward;
  (c) the forecast-value baseline computes on a real window and is reported with
      provenance — its sign is a finding, not a gate (formulation §R2.5).

Network setup (this machine): a TLS-intercepting proxy means uv-Python needs the
Keychain roots — see docs/specs/R1.4b-entsoe-loader.md § "Environment note".
"""

import os

import numpy as np
import pandas as pd
import pytest

from bess.assets.battery import BatterySpec
from bess.data.entsoe import fetch_day_ahead
from bess.stochastic import value_of_stochastic_solution, vss_across_windows, window_sets

pytestmark = pytest.mark.integration

requires_token = pytest.mark.skipif(
    not os.environ.get("ENTSOE_API_TOKEN"),
    reason="ENTSOE_API_TOKEN not set — live ENTSO-E integration test skipped (never runs in CI)",
)

TOL = 1e-6

# Same asset as the committed R2.3/R2.5 figures (2 MWh / 1 MW anchored half-full).
_BATT = BatterySpec(capacity=2.0, soc_initial=0.5, soc_terminal=0.5)

# 28 history days + 5 weeks of scored windows, hourly (pre-15-min switch).
_START = pd.Timestamp("2024-04-01", tz="UTC")
_END = pd.Timestamp("2024-06-04 23:00", tz="UTC")
_KW = dict(history_days=28, n_scenarios=30, seed=0)


def _real_prices() -> pd.Series:
    return fetch_day_ahead("NL", _START, _END)


@requires_token
def test_vss_distribution_median_nonnegative_on_real_weeks():
    prices = _real_prices()
    results = vss_across_windows(prices, _BATT, rho=0.5, **_KW)

    # At least four disjoint weeks of scored windows.
    assert len(results) >= 28
    vss = np.array([w.vss_oos for w in results])
    assert float(np.median(vss)) >= -TOL
    # Windows are the study's unit: consecutive UTC days, each internally consistent.
    for w in results:
        assert w.vss_oos == pytest.approx(w.rp_oos - w.eev_oos, abs=TOL)


@requires_token
def test_in_sample_ordering_on_every_real_window():
    prices = _real_prices()
    for _start, train, _evaluation in window_sets(prices, **_KW):
        res = value_of_stochastic_solution(train, _BATT, rho=0.5)
        assert res.eev <= res.rp + TOL
        assert res.rp <= res.ws + TOL


@requires_token
def test_pinball_skill_beats_seasonal_naive_live():
    pytest.importorskip("lightgbm")
    pytest.importorskip("mapie")
    from bess.forecaster.evaluate import walk_forward_pinball_skill

    prices = _real_prices()
    skill = walk_forward_pinball_skill(prices, confidence_level=0.9)
    # Accuracy, not calibration: the conformal quantiles beat the naive point
    # used as a degenerate quantile, at both interval edges.
    assert skill.skill_lower < 1.0
    assert skill.skill_upper < 1.0


@requires_token
def test_forecast_value_reports_on_real_window(capsys):
    pytest.importorskip("lightgbm")
    pytest.importorskip("mapie")
    from bess.stochastic import forecast_value

    prices = _real_prices()
    fv = forecast_value(prices, _BATT, **_KW, rho=0.5)
    assert np.isfinite(fv.fv_eur)
    assert fv.fv_eur == pytest.approx(fv.profit_conformal_eur - fv.profit_naive_eur, abs=TOL)
    # Reported with provenance, not sign-asserted (formulation §R2.5).
    print(
        f"\nforecast value (real NL, window {_END.date()}): "
        f"conformal {fv.profit_conformal_eur:.2f} EUR, naive {fv.profit_naive_eur:.2f} EUR, "
        f"FV {fv.fv_eur:+.2f} EUR"
    )
