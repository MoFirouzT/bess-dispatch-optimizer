"""Drift-monitor gates (R2.1b) — regime shift vs. model staleness.

Pure numpy/pandas: runs without the ``forecast`` dependency group. Honest framing
(spec § "Honest gate framing"): these are **behavioral** gates — the regime-shift
and staleness patterns are designed, and the monitor is checked to separate them.
They prove the classification logic behaves as specified, not a distribution-free
truth.
"""

from __future__ import annotations

import numpy as np

from bess.forecaster import DriftMonitor, DriftStatus, classify_drift, psi


def test_psi_zero_on_identical_and_grows_with_shift():
    rng = np.random.default_rng(0)
    ref = rng.normal(50, 10, 2000)
    assert psi(ref, ref) < 1e-6  # identical ⇒ ≈ 0
    small = psi(ref, ref + 5)
    large = psi(ref, ref + 30)
    assert 0.0 < small < large  # farther shift ⇒ larger PSI


def test_classify_precedence_staleness_wins_when_both_fire():
    # error_ratio high AND psi high → STALENESS (checked first, ADR-0015).
    both = classify_drift(forecaster_mae=20.0, naive_mae=10.0, psi_value=0.5)
    assert both.status is DriftStatus.STALENESS

    stale = classify_drift(forecaster_mae=15.0, naive_mae=10.0, psi_value=0.02)
    assert stale.status is DriftStatus.STALENESS

    regime = classify_drift(forecaster_mae=20.0, naive_mae=19.0, psi_value=0.35)
    assert regime.status is DriftStatus.REGIME_SHIFT

    healthy = classify_drift(forecaster_mae=5.0, naive_mae=6.0, psi_value=0.03)
    assert healthy.status is DriftStatus.HEALTHY


def test_monitor_discriminates_regime_shift_from_staleness():
    rng = np.random.default_rng(7)
    reference = rng.normal(50.0, 10.0, 1000)
    monitor = DriftMonitor(reference_prices=reference)

    # (a) REGIME SHIFT: market level jumped +40; both the (stale-to-old-level)
    # forecaster and the seasonal-naive predict the OLD level, so both are ~equally
    # wrong (ratio ≈ 1) while the input distribution moved (PSI high).
    base = rng.normal(50.0, 10.0, 300)
    realized_regime = base + 40.0
    point_regime = base.copy()  # forecaster predicts old level
    naive_regime = base.copy()  # last-week naive also old level
    regime = monitor.assess(realized_regime, point_regime, naive_regime)
    assert regime.status is DriftStatus.REGIME_SHIFT

    # (b) STALENESS: inputs stable (PSI low), naive tracks well, but the forecaster's
    # residuals are inflated — model-specific decay (ratio high).
    realized_stale = rng.normal(50.0, 10.0, 300)
    naive_stale = realized_stale + rng.normal(0.0, 1.5, 300)  # tracks closely
    point_stale = realized_stale + rng.normal(0.0, 20.0, 300)  # decayed
    stale = monitor.assess(realized_stale, point_stale, naive_stale)
    assert stale.status is DriftStatus.STALENESS

    # The two episodes are classified differently (the whole point).
    assert regime.status is not stale.status


def test_monitor_reports_coverage_and_healthy_case():
    rng = np.random.default_rng(3)
    reference = rng.normal(50.0, 10.0, 1000)
    monitor = DriftMonitor(reference_prices=reference)

    realized = rng.normal(50.0, 10.0, 300)
    point = realized + rng.normal(0.0, 2.0, 300)  # accurate
    naive = realized + rng.normal(0.0, 2.0, 300)  # comparable
    lower, upper = realized - 20.0, realized + 20.0  # wide ⇒ high coverage
    report = monitor.assess(realized, point, naive, lower=lower, upper=upper)

    assert report.status is DriftStatus.HEALTHY
    assert report.coverage is not None and report.coverage > 0.9
