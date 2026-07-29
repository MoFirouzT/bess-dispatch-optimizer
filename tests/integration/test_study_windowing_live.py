"""Integration — R2.7 value studies re-measured over the full span.

Contract: docs/specs/study-windowing.md § "Statistical gates".
Token-gated *and* `studies`-marked: this module scores 260 delivery days per study and
runs about an hour, so it is deselected from the routine live tier
(`-m "integration and not studies"`) and run deliberately. Nothing fetched here is
committed; real prices are pulled at runtime and discarded.

What it proves on *real* prices, across 2022 to 2025 rather than one 2024 quarter:

  (a) the per-window out-of-sample VSS median is not *significantly* negative, on NL
      and again on BE, under a block bootstrap that treats the fold block rather than
      the window as the resampling unit (windows inside a block are consecutive days
      and share 27 of 28 training days, so a per-window sign test overstates the
      evidence: that was the R2.5 gate's flaw, not just its window's);
  (b) every scored window still obeys the in-sample Birge-Louveaux ordering;
  (c) forecast value, tail value and bid-curve value are **reported** with their
      per-year breakdown, never sign-asserted. Whether they convert to euros is the
      finding these studies exist to measure, and a sign that moves under
      re-windowing is a result rather than a failure.

The window selection is the R2.1d fold layout reused verbatim, so these euro numbers
and the forecaster's pinball skill are measured on the identical 260 days.
"""

import os

import numpy as np
import pandas as pd
import pytest
from span import span_fold_days, span_prices

from bess.assets.battery import BatterySpec
from bess.stochastic import value_of_stochastic_solution
from bess.studies import (
    bid_curve_value_across_windows,
    summarize_by_block,
    summarize_by_year,
    tail_value_across_windows,
    vss_across_windows,
    window_sets,
)

pytestmark = [pytest.mark.integration, pytest.mark.studies]

requires_token = pytest.mark.skipif(
    not os.environ.get("ENTSOE_API_TOKEN"),
    reason="ENTSOE_API_TOKEN not set — live ENTSO-E integration test skipped (never runs in CI)",
)

TOL = 1e-6

# Same asset as every committed R2.3 / R2.5 figure (2 MWh / 1 MW anchored half-full).
_BATT = BatterySpec(capacity=2.0, soc_initial=0.5, soc_terminal=0.5)

# Unchanged from R2.5 / R2.5b / R2.6 on purpose: this phase varies the window set and
# nothing else, so a moved number has one candidate explanation rather than five.
_KW = dict(history_days=28, n_scenarios=30, seed=0)
_TAIL_RHOS = (0.25, 1.0)
_BC_RHOS = (0.25, 1.0)


def _blocks_of(days: pd.DatetimeIndex) -> np.ndarray:
    """Label each day with its fold block: a new block wherever the day sequence jumps."""
    gaps = (days[1:] - days[:-1]) != pd.Timedelta(days=1)
    return np.concatenate([[0], np.cumsum(np.asarray(gaps))])


def _report(name: str, starts, values, *, zone: str) -> None:
    """Print the distribution, per year as well as pooled.

    A gate that only decides pass/fail publishes nothing, and a claim nobody
    re-measures is a claim that rots. The studies pages quote these lines.
    """
    v = np.asarray(values, dtype=float)
    days = pd.DatetimeIndex(starts)
    s = summarize_by_block(v, _blocks_of(days))
    print(
        f"\n{name} ({zone}, {s.n_windows} windows, {days.min():%Y-%m-%d} to {days.max():%Y-%m-%d}):"
        f"\n  median {s.median:+.2f} EUR, CI [{s.median_ci[0]:+.2f}, {s.median_ci[1]:+.2f}], "
        f"{s.share_positive:.0%} > 0, quartiles [{s.q25:+.2f}, {s.q75:+.2f}]"
    )
    for year, y in sorted(summarize_by_year(v, list(days)).items()):
        print(
            f"  {year}: n={y.n_windows:3d}  median {y.median:+8.2f}  "
            f"CI [{y.median_ci[0]:+8.2f}, {y.median_ci[1]:+8.2f}]  {y.share_positive:.0%} > 0"
        )


@requires_token
@pytest.mark.parametrize("zone", ["NL", "BE"])
def test_vss_median_not_significantly_negative_across_the_span(zone):
    """The one gated euro claim, on both markets.

    BE is gated rather than merely reported for the reason R2.1d gates its own BE
    check: NL alone cannot separate "the stochastic layer earns its keep" from "NL
    happens to reward it".
    """
    prices = span_prices(zone)
    days = span_fold_days(prices)
    results = vss_across_windows(prices, _BATT, rho=0.5, only_days=days, **_KW)

    assert len(results) == len(days) == 260, (
        f"{len(results)} scored windows against {len(days)} selected days: the fold "
        "layout must promise and deliver the same number (spec build task 0)"
    )
    vss = np.array([w.vss_oos for w in results])
    starts = pd.DatetimeIndex([w.window_start for w in results])

    _report("VSS", starts, vss, zone=zone)
    for w in results:
        assert w.vss_oos == pytest.approx(w.rp_oos - w.eev_oos, abs=TOL)

    # Fail only on a genuine collapse to systematically negative value, not on
    # sampling noise. Not tuned to pass: the interval is computed from the data.
    s = summarize_by_block(vss, _blocks_of(starts))
    assert s.median_ci[1] >= 0.0, (
        f"{zone}: the whole 95% block-bootstrap interval on the per-window VSS median "
        f"[{s.median_ci[0]:+.2f}, {s.median_ci[1]:+.2f}] lies below zero "
        f"(median {s.median:+.2f}, {s.share_positive:.0%} positive): "
        "the stochastic layer's value has collapsed on real data"
    )


@requires_token
def test_in_sample_ordering_on_every_scored_window():
    """EEV <= RP <= WS on each of the 260 training sets, unchanged from R2.5."""
    prices = span_prices("NL")
    days = span_fold_days(prices)
    checked = 0
    for _start, train, _evaluation in window_sets(prices, only_days=days, **_KW):
        res = value_of_stochastic_solution(train, _BATT, rho=0.5)
        assert res.eev <= res.rp + TOL
        assert res.rp <= res.ws + TOL
        checked += 1
    assert checked == 260


@requires_token
@pytest.mark.parametrize("zone", ["NL", "BE"])
def test_forecast_value_reported_across_the_span(zone):
    """Forecast value, reported with provenance and by regime. Its sign is the finding."""
    pytest.importorskip("lightgbm")
    pytest.importorskip("mapie")
    from bess.studies import fv_across_windows

    prices = span_prices(zone)
    days = span_fold_days(prices)
    windows = fv_across_windows(prices, _BATT, rho=0.5, only_days=days, **_KW)

    assert len(windows) >= 200, f"only {len(windows)} scoreable FV windows of {len(days)}"
    fvs = np.array([w.fv_eur for w in windows])
    assert np.isfinite(fvs).all()
    for w in windows:
        assert w.fv_eur == pytest.approx(w.profit_conformal_eur - w.profit_naive_eur, abs=TOL)

    _report("Forecast value", [w.window_start for w in windows], fvs, zone=zone)


@requires_token
@pytest.mark.parametrize("rho", _TAIL_RHOS)
def test_tail_value_reported_across_the_span(rho):
    """Tail value at both recourse budgets, NL only (see the spec's runtime budget)."""
    prices = span_prices("NL")
    days = span_fold_days(prices)
    windows = tail_value_across_windows(prices, _BATT, rho=rho, only_days=days, **_KW)

    assert len(windows) == 260
    tv = np.array([w.tv_eur for w in windows])
    assert np.isfinite(tv).all()
    _report(f"Tail value (rho={rho})", [w.window_start for w in windows], tv, zone="NL")


@requires_token
@pytest.mark.parametrize("rho", _BC_RHOS)
def test_bid_curve_value_reported_across_the_span(rho):
    """Bid-curve value at both recourse budgets, NL only.

    Windows whose evaluation program is infeasible are skipped by the study, so this
    one cannot assert the full 260; what it asserts is that the skipping stays a
    minority, which is the condition under which the reported distribution means
    anything.
    """
    prices = span_prices("NL")
    days = span_fold_days(prices)
    windows = bid_curve_value_across_windows(
        prices, _BATT, history_days=28, n_scenarios=10, rho=rho, seed=0, only_days=days
    )

    assert len(windows) >= 0.6 * len(days), (
        f"only {len(windows)} of {len(days)} windows scoreable at rho={rho}: too many "
        "infeasible evaluation programs for the distribution to describe the span"
    )
    bcv = np.array([w.bcv_eur for w in windows])
    assert np.isfinite(bcv).all()
    for w in windows:
        assert w.delivery_gap_curve_mwh >= -1e-9
        assert w.delivery_gap_scalar_mwh >= -1e-9

    _report(f"Bid-curve value (rho={rho})", [w.window_start for w in windows], bcv, zone="NL")
    gaps = np.array([w.delivery_gap_curve_mwh for w in windows])
    print(f"  delivery gap (curve): median {np.median(gaps):.2f} MWh/day, max {gaps.max():.2f}")
