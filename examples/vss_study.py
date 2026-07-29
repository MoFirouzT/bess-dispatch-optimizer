#!/usr/bin/env python3
"""Value-evaluation study (R2.5) — the per-window out-of-sample VSS distribution.

Repeats the docs/decisions/risk-aware-two-stage-design.md out-of-sample VSS measurement over every
UTC-day window of a
price series (train on the trailing days, score the fixed commitments on the
realized path) and reports the distribution: median, quartiles, share of windows
above zero. This is the honest form of the R2.3 value claim — a property of the
market, not of one designed instance.

The **committed** figure is built from real ENTSO-E NL prices. To reproduce it,
set a token and run:

    ENTSOE_API_TOKEN=... uv run --group examples python examples/vss_study.py

Without a token it falls back to a **synthetic** set of designed days (a common
cheap charge hour, a random later peak) that shows the mechanism; numbers are
illustrative, not a gate; no real price data is committed (only the chart).

With the ``forecast`` group installed, the script also reports the R2.5
forecast-value baseline (conformal vs. seasonal-naive scenarios, in euros) and
the walk-forward pinball skill on the same series; both are skipped cleanly
without it.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd

from bess.assets.battery import BatterySpec
from bess.data.entsoe import fetch_day_ahead
from bess.forecaster.evaluate import rolling_origin_folds
from bess.studies import fold_days, summarize_by_year, vss_across_windows

HISTORY_DAYS = 28
N_SCENARIOS = 30
RHO = 0.5
N_SYNTH_DAYS = 40
# The forecast-value + pinball section needs the forecast group and a series long
# enough for the forecaster's week-scale lags; the smoke test turns it off.
RUN_FORECAST_BASELINE = True

#: ``fast`` (the default) samples every ``FAST_BLOCK_STRIDE``-th fold block, so the
#: script finishes in a few minutes; ``full`` scores all 260 days and is what the
#: committed figures are built from. Both still span 2022 to 2025: fast mode strides
#: across the blocks rather than truncating the range, so a preview cannot accidentally
#: describe one regime.
MODE = "fast"
FAST_BLOCK_STRIDE = 4

FIG_DIR = Path(__file__).resolve().parent.parent / "docs" / "figures"
#: Where ``fast`` mode writes. Deliberately **not** ``docs/figures``: a figure built
#: from a subsample must not be committable over a published one, and a rule enforced
#: by the output path survives where a warning in the console does not. ``build/`` is
#: gitignored.
PREVIEW_DIR = Path(__file__).resolve().parent.parent / "build" / "figure-previews"
# Same asset as the R2.3 frontier/VSS-curve figures: 2 MWh / 1 MW anchored
# half-full, so the day-ahead commitment has genuine freedom in both directions.
BATTERY = BatterySpec(capacity=2.0, soc_initial=0.5, soc_terminal=0.5)


def _real_series(zone: str = "NL") -> tuple[pd.Series, pd.DatetimeIndex]:
    """Real day-ahead over the R2.7 span, plus the 260 days the studies score.

    Returns the whole 2021-2025 series (the trailing history each window needs) and
    the fold selection laid over its **complete** days. Folds are placed over complete
    days only because the span's final day carries a single hour, and a window is one
    full day or it is not a window (spec study-windowing.md, build task 0).
    """
    prices = fetch_day_ahead(
        zone, pd.Timestamp("2021-01-01", tz="UTC"), pd.Timestamp("2025-09-30", tz="UTC")
    )
    idx = pd.DatetimeIndex(prices.index)
    complete = pd.DatetimeIndex(
        [day for day, chunk in prices.groupby(idx.normalize()) if len(chunk) == 24]
    )
    folds = rolling_origin_folds(complete, n_folds=52, test_days=5, train_days=365, spacing="even")
    return prices, fold_days(folds)


def _synthetic_series(seed: int = 0) -> pd.Series:
    """Designed days (cheap t0, a peak at a random early hour, flat otherwise):
    the R2.3 value-generating structure, repeated so windows exist."""
    rng = np.random.default_rng(seed)
    days = []
    for _ in range(N_SYNTH_DAYS):
        p = rng.uniform(8.0, 12.0, size=24)
        p[0] = rng.uniform(3.0, 6.0)
        p[rng.integers(1, 4)] = rng.uniform(45.0, 60.0)
        days.append(p)
    values = np.concatenate(days)
    idx = pd.date_range("2024-03-01", periods=len(values), freq="h", tz="UTC")
    return pd.Series(values, index=idx)


def main() -> None:
    if MODE not in ("fast", "full"):
        raise SystemExit(f"MODE must be 'fast' or 'full'; got {MODE!r}")
    out_dir = FIG_DIR if MODE == "full" else PREVIEW_DIR

    if os.environ.get("ENTSOE_API_TOKEN"):
        prices, days = _real_series()
        tag = f"real NL, {len(days)} days over 2022-2025"
        if MODE == "fast":
            tag += " (preview subsample)"
    else:
        prices, days = _synthetic_series(), None
        tag = "synthetic"

    if MODE == "fast":
        print(
            "mode=fast: a strided subsample, written to build/figure-previews/.\n"
            "  The committed figures come from `--mode full` (about 15 minutes).\n"
        )
    print(f"VSS study — {tag} ({len(prices)} hourly prices)\n")

    results = vss_across_windows(
        prices, BATTERY, history_days=HISTORY_DAYS, n_scenarios=N_SCENARIOS, rho=RHO,
        only_days=days,
    )  # fmt: skip
    vss = np.array([w.vss_oos for w in results])
    q1, med, q3 = np.percentile(vss, [25, 50, 75])
    print(f"{len(vss)} windows (history {HISTORY_DAYS} d, {N_SCENARIOS} scenarios, rho={RHO})")
    print(f"median VSS      {med:8.2f} EUR/window")
    print(f"quartiles       [{q1:.2f}, {q3:.2f}]")
    print(f"share > 0       {np.mean(vss > 0):8.0%}")
    print(f"min / max       {vss.min():.2f} / {vss.max():.2f}")

    from bess.viz.stochastic_plots import plot_vss_distribution

    out_dir.mkdir(parents=True, exist_ok=True)
    fig = plot_vss_distribution(vss, title=f"Per-window out-of-sample VSS — {tag}")
    path = out_dir / "example-vss-distribution.svg"
    fig.savefig(path, format="svg", bbox_inches="tight")
    print(f"\nwrote {path} ({tag})")

    # Optional: the forecast-value baseline + pinball skill (forecast group only).
    if not RUN_FORECAST_BASELINE:
        return
    try:
        import lightgbm  # noqa: F401
        import mapie  # noqa: F401
    except ImportError:
        print("\nforecast group not installed — skipping forecast-value + pinball skill")
        return
    from bess.forecaster.evaluate import walk_forward_pinball_skill
    from bess.studies import forecast_value

    fv = forecast_value(
        prices, BATTERY, history_days=HISTORY_DAYS, n_scenarios=N_SCENARIOS, rho=RHO
    )  # the single-window wrapper: the last scoreable day of the series
    print("\nForecast value (last window; conformal vs seasonal-naive scenarios)")
    print(f"conformal plan  {fv.profit_conformal_eur:8.2f} EUR")
    print(f"naive plan      {fv.profit_naive_eur:8.2f} EUR")
    print(f"FV              {fv.fv_eur:8.2f} EUR  (reported, not sign-asserted)")

    skill = walk_forward_pinball_skill(prices)
    print("\nPinball skill vs seasonal-naive (walk-forward, interval edges)")
    print(
        f"tau={skill.tau_lower:.3f}: conformal {skill.conformal_lower:.2f}"
        f" vs naive {skill.naive_lower:.2f}  -> skill {skill.skill_lower:.2f}"
    )
    print(f"tau={skill.tau_upper:.3f}: conformal {skill.conformal_upper:.2f}"
          f" vs naive {skill.naive_upper:.2f}  -> skill {skill.skill_upper:.2f}")  # fmt: skip

    from bess.studies import fv_across_windows

    fv_windows = fv_across_windows(
        prices, BATTERY, history_days=HISTORY_DAYS, n_scenarios=N_SCENARIOS, rho=RHO,
        only_days=days,
    )  # fmt: skip
    fvs = np.array([w.fv_eur for w in fv_windows])
    fq1, fmed, fq3 = np.percentile(fvs, [25, 50, 75])
    print(f"\nForecast-value distribution ({len(fvs)} windows, forecaster refit weekly)")
    print(f"median FV       {fmed:8.2f} EUR/window")
    print(f"quartiles       [{fq1:.2f}, {fq3:.2f}]")
    print(f"share > 0       {np.mean(fvs > 0):8.0%}")
    print(f"min / max       {fvs.min():.2f} / {fvs.max():.2f}")

    fig_fv = plot_vss_distribution(
        fvs,
        title=f"Per-window forecast value, conformal vs seasonal-naive — {tag}",
        xlabel="FV = conformal-plan profit − naive-plan profit, per window (EUR)",
    )
    fv_path = out_dir / "example-fv-distribution.svg"
    fig_fv.savefig(fv_path, format="svg", bbox_inches="tight")
    print(f"\nwrote {fv_path} ({tag})")

    # R2.7: the same two distributions split by regime. A pooled median can hide a
    # finding that holds in one price regime and not another, and each year's interval
    # is what stops a reader taking four points for a trend.
    from bess.viz.stochastic_plots import plot_value_by_regime

    vss_years = summarize_by_year(vss, [w.window_start for w in results])
    fv_years = summarize_by_year(fvs, [w.window_start for w in fv_windows])
    fig_reg = plot_value_by_regime(
        vss_years,
        series=[vss_years, fv_years],
        labels=["stochastic value", "forecast value"],
        title=f"Per-window value by year, with block-bootstrap intervals — {tag}",
    )
    reg_path = out_dir / "example-value-by-regime.svg"
    fig_reg.savefig(reg_path, format="svg", bbox_inches="tight")
    print(f"\nwrote {reg_path} ({tag})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument(
        "--mode",
        choices=("fast", "full"),
        default=MODE,
        help=(
            "fast (default): a strided block subsample, a few minutes, written to "
            "build/figure-previews/. full: all 260 days, about 15 minutes, writes the "
            "committed figures in docs/figures/."
        ),
    )
    MODE = parser.parse_args().mode
    main()
