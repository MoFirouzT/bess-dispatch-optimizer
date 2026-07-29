"""Integration — R2.8: how reproducible is a published value median?

Contract: docs/specs/draw-noise.md § "Statistical gates".
Token-gated and `studies`-marked: it runs each study once per seed, so it is deselected
from the routine live tier and run deliberately. Nothing fetched here is committed.

**Reported, never asserted.** There is no threshold a seed spread should pass. The
width *is* the finding, and gating it against a bound would mean picking the bound after
seeing the number, which is not a gate. The assertions cover only that every run
completed and produced a finite median, so a silently-failing study cannot masquerade as
a reproducible one.

The window set is R2.7's, held fixed: varying the seed while anything else moves would
measure the two together, which is the mistake R2.7's own isolation run existed to undo.
"""

import os

import numpy as np
import pandas as pd
import pytest
from span import span_fold_days, span_prices

from bess.assets.battery import BatterySpec
from bess.studies import summarize_across_seeds, summarize_by_block, vss_across_windows

pytestmark = [pytest.mark.integration, pytest.mark.studies]

requires_token = pytest.mark.skipif(
    not os.environ.get("ENTSOE_API_TOKEN"),
    reason="ENTSOE_API_TOKEN not set — live ENTSO-E integration test skipped (never runs in CI)",
)

_BATT = BatterySpec(capacity=2.0, soc_initial=0.5, soc_terminal=0.5)
_KW = dict(history_days=28, n_scenarios=30)

#: 2.7 min per VSS run against 7.2 for FV, so the budgets differ (spec § Parameters).
_VSS_SEEDS = range(10)
_FV_SEEDS = range(6)


def _blocks_of(days: pd.DatetimeIndex) -> np.ndarray:
    gaps = (days[1:] - days[:-1]) != pd.Timedelta(days=1)
    return np.concatenate([[0], np.cumsum(np.asarray(gaps))])


def _report(name: str, medians: dict[int, float], shares: dict[int, float]) -> None:
    s = summarize_across_seeds(medians)
    sh = summarize_across_seeds(shares)
    print(
        f"\n{name} over {s.n_seeds} seeds (R2.7 window set, NL):"
        f"\n  median  mean {s.mean_median:+.2f}  sd {s.sd_median:.2f}  "
        f"range [{s.min_median:+.2f}, {s.max_median:+.2f}]  spread {s.spread:.2f} EUR"
        f"\n  share>0 mean {sh.mean_median:.3f}  spread {sh.spread:.3f}"
    )


@requires_token
def test_vss_median_reproducibility_across_seeds():
    """How far the stochastic-value headline travels on identical days."""
    prices = span_prices("NL")
    days = span_fold_days(prices)

    medians, shares = {}, {}
    for seed in _VSS_SEEDS:
        w = vss_across_windows(prices, _BATT, rho=0.5, seed=seed, only_days=days, **_KW)
        assert len(w) == len(days), f"seed {seed} scored {len(w)} of {len(days)} days"
        v = np.array([x.vss_oos for x in w])
        assert np.isfinite(v).all(), f"seed {seed} produced a non-finite window value"
        medians[seed] = float(np.median(v))
        shares[seed] = float(np.mean(v > 0))

    _report("VSS", medians, shares)

    # The comparison that gives the width meaning: the window interval answers a
    # different question and cannot absorb this one, because it resamples values that
    # all came from a single seed.
    w0 = vss_across_windows(prices, _BATT, rho=0.5, seed=0, only_days=days, **_KW)
    s0 = summarize_by_block(
        np.array([x.vss_oos for x in w0]),
        _blocks_of(pd.DatetimeIndex([x.window_start for x in w0])),
    )
    width = s0.median_ci[1] - s0.median_ci[0]
    print(
        f"  window-CI width at seed 0: {width:.2f} EUR "
        f"[{s0.median_ci[0]:+.2f}, {s0.median_ci[1]:+.2f}]"
    )

    assert np.isfinite(summarize_across_seeds(medians).spread)


@requires_token
def test_forecast_value_median_reproducibility_across_seeds():
    """The same for forecast value, where the seed also drives the forecaster fit.

    The reported width therefore covers model-fitting noise as well as draw noise, which
    is the honest scope for "re-run the published command and see how far it moves".
    Separating the two would need the seeds decoupled in the interface (spec, Decisions).
    """
    pytest.importorskip("lightgbm")
    pytest.importorskip("mapie")
    from bess.studies import fv_across_windows

    prices = span_prices("NL")
    days = span_fold_days(prices)

    medians, shares = {}, {}
    for seed in _FV_SEEDS:
        w = fv_across_windows(prices, _BATT, rho=0.5, seed=seed, only_days=days, **_KW)
        assert len(w) >= 200, f"seed {seed} scored only {len(w)} windows"
        v = np.array([x.fv_eur for x in w])
        assert np.isfinite(v).all(), f"seed {seed} produced a non-finite window value"
        medians[seed] = float(np.median(v))
        shares[seed] = float(np.mean(v > 0))

    _report("Forecast value", medians, shares)
    assert np.isfinite(summarize_across_seeds(medians).spread)
