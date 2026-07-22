#!/usr/bin/env python3
"""Value-evaluation study (R2.5) — the per-window out-of-sample VSS distribution.

Repeats the ADR-0021 out-of-sample VSS measurement over every UTC-day window of a
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

import os
from pathlib import Path

import numpy as np
import pandas as pd

from bess.assets.battery import BatterySpec
from bess.data.entsoe import fetch_day_ahead
from bess.stochastic import vss_across_windows

HISTORY_DAYS = 28
N_SCENARIOS = 30
RHO = 0.5
N_SYNTH_DAYS = 40
# The forecast-value + pinball section needs the forecast group and a series long
# enough for the forecaster's week-scale lags; the smoke test turns it off.
RUN_FORECAST_BASELINE = True
FIG_DIR = Path(__file__).resolve().parent.parent / "docs" / "figures"
# Same asset as the R2.3 frontier/VSS-curve figures: 2 MWh / 1 MW anchored
# half-full, so the day-ahead commitment has genuine freedom in both directions.
BATTERY = BatterySpec(capacity=2.0, soc_initial=0.5, soc_terminal=0.5)


def _real_series() -> pd.Series:
    """Real NL day-ahead, 2024-Q2 (hourly, pre-15-min switch): 28 history days
    feeding ~63 scored windows."""
    return fetch_day_ahead(
        "NL", pd.Timestamp("2024-04-01", tz="UTC"), pd.Timestamp("2024-06-30 23:00", tz="UTC")
    )


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
    if os.environ.get("ENTSOE_API_TOKEN"):
        prices, tag = _real_series(), "real NL, 2024-Q2"
    else:
        prices, tag = _synthetic_series(), "synthetic"
    print(f"VSS study — {tag} ({len(prices)} hourly prices)\n")

    results = vss_across_windows(
        prices, BATTERY, history_days=HISTORY_DAYS, n_scenarios=N_SCENARIOS, rho=RHO
    )
    vss = np.array([w.vss_oos for w in results])
    q1, med, q3 = np.percentile(vss, [25, 50, 75])
    print(f"{len(vss)} windows (history {HISTORY_DAYS} d, {N_SCENARIOS} scenarios, rho={RHO})")
    print(f"median VSS      {med:8.2f} EUR/window")
    print(f"quartiles       [{q1:.2f}, {q3:.2f}]")
    print(f"share > 0       {np.mean(vss > 0):8.0%}")
    print(f"min / max       {vss.min():.2f} / {vss.max():.2f}")

    from bess.viz.stochastic_plots import plot_vss_distribution

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig = plot_vss_distribution(vss, title=f"Per-window out-of-sample VSS — {tag}")
    path = FIG_DIR / "example-vss-distribution.svg"
    fig.savefig(path, format="svg", bbox_inches="tight")
    print(f"\nwrote {path.name} to docs/figures/ ({tag})")

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
    from bess.stochastic import forecast_value

    fv = forecast_value(
        prices, BATTERY, history_days=HISTORY_DAYS, n_scenarios=N_SCENARIOS, rho=RHO
    )
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


if __name__ == "__main__":
    main()
