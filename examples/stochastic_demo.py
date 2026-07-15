#!/usr/bin/env python3
"""Stochastic layer demo (R2.3) — the risk-return frontier and the VSS curve.

Builds a synthetic day-ahead scenario set (a common cheap charge hour, a random
later peak), then:

- sweeps the risk weight λ to trace the mean-CVaR frontier (expected profit vs
  downside), and
- sweeps the recourse budget ρ to show the value of the stochastic solution rise
  from 0 (no recourse) to a positive interior and back toward 0 (unlimited
  recourse) — the escape from the VSS = 0 trap.

The **committed** figures are built from real ENTSO-E NL prices (each historical
day is one equiprobable 24-hour scenario). To reproduce them, set a token and run:

    ENTSOE_API_TOKEN=... uv run python examples/stochastic_demo.py

Without a token it falls back to designed **synthetic** scenario sets (a common
cheap charge hour, a random later peak) that trace the same shapes. Numbers are
illustrative, not a gate; no real price data is committed (only the charts). Run:

    uv run python examples/stochastic_demo.py
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

from bess.assets.battery import BatterySpec
from bess.data.entsoe import fetch_day_ahead
from bess.scenarios import ScenarioSet
from bess.stochastic import solve_stochastic, value_of_stochastic_solution

HORIZON = 4
N_SCENARIOS = 80
# The mean-CVaR frontier is piecewise-linear in λ and its transition lives at low
# λ, so the sweep is dense there (a coarse sweep would collapse to two points).
LAMBDAS = [0.0, 0.02, 0.04, 0.06, 0.08, 0.1, 0.15, 0.2, 0.3, 0.5, 0.9]
RHOS = [0.0, 0.1, 0.2, 0.3, 0.4, 0.6, 0.8, 1.2, 2.0]
FRONTIER_ALPHA = 0.85
FRONTIER_RHO = 0.15
FIG_DIR = Path(__file__).resolve().parent.parent / "docs" / "figures"
BATTERY = BatterySpec(capacity=2.0, soc_initial=0.5, soc_terminal=0.5)


def _make_set(paths: np.ndarray) -> ScenarioSet:
    index = pd.date_range("2026-01-01", periods=paths.shape[1], freq="h", tz="UTC")
    return ScenarioSet(paths=paths, probs=np.full(len(paths), 1.0 / len(paths)), index=index)


def _frontier_scenarios(seed: int = 3) -> ScenarioSet:
    # A "gamble" set: a common cheap charge hour, then either a rare morning jackpot
    # of widely varying size (t1) or the common evening peak (t3). A morning-tilted
    # commitment chases the jackpot's upside at the cost of the common days' downside,
    # so risk aversion genuinely bends the first-stage decision (a graded frontier).
    rng = np.random.default_rng(seed)
    days = []
    for _ in range(N_SCENARIOS):
        p = rng.uniform(9.0, 11.0, size=HORIZON)
        p[0] = rng.uniform(4.0, 6.0)
        if rng.random() < 0.35:
            p[1] = rng.uniform(25.0, 95.0)
        else:
            p[3] = rng.uniform(28.0, 42.0)
        days.append(p)
    return _make_set(np.asarray(days))


def _vss_scenarios(seed: int = 0) -> ScenarioSet:
    # A common cheap charge hour + a random later peak: a single commitment banks the
    # charge, recourse adapts the discharge. VSS rises then falls as the budget grows,
    # so this set traces the VSS-vs-ρ shape cleanly.
    rng = np.random.default_rng(seed)
    days = []
    for _ in range(N_SCENARIOS):
        p = rng.uniform(8.0, 12.0, size=HORIZON)
        p[0] = rng.uniform(3.0, 6.0)
        p[rng.integers(1, HORIZON)] = rng.uniform(45.0, 60.0)
        days.append(p)
    return _make_set(np.asarray(days))


def _real_daily_scenarios() -> ScenarioSet:
    """Real NL day-ahead reshaped into equiprobable 24-hour scenarios.

    A 45-day 2024-Q2 window (hourly, before the 2025-10 SDAC 15-min switch); each
    calendar day is one price-path scenario — a historical distribution over day
    shapes, the same construction the live integration test uses.
    """
    prices = fetch_day_ahead(
        "NL", pd.Timestamp("2024-04-01", tz="UTC"), pd.Timestamp("2024-05-31 23:00", tz="UTC")
    )
    values = prices.to_numpy(dtype=float)
    usable = (len(values) // 24) * 24
    paths = values[:usable].reshape(-1, 24)[:45]
    index = pd.date_range("2026-01-01", periods=24, freq="h", tz="UTC")
    return ScenarioSet(paths=paths, probs=np.full(len(paths), 1.0 / len(paths)), index=index)


def _configure():
    """Pick the scenario sets and sweep grids: real NL if a token is set, else the
    designed synthetic sets. Returns ``(frontier_scen, vss_scen, lambdas, rhos,
    alpha, frho, tag)``; on real data one daily set serves both sweeps."""
    if os.environ.get("ENTSOE_API_TOKEN"):
        scen = _real_daily_scenarios()
        lambdas = [0.0, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.9]
        rhos = [0.0, 0.1, 0.2, 0.3, 0.5, 0.8, 1.2, 2.0]
        return scen, scen, lambdas, rhos, 0.9, 0.3, "real NL, 2024-Q2"
    return (
        _frontier_scenarios(), _vss_scenarios(), LAMBDAS, RHOS,
        FRONTIER_ALPHA, FRONTIER_RHO, "synthetic",
    )  # fmt: skip


def main() -> None:
    frontier_scen, vss_scen, lambdas, rhos, alpha, frho, tag = _configure()
    print(f"Stochastic demo — {tag} scenario set\n")

    # Risk-return frontier: sweep λ (at a fixed budget).
    exp_profit, cvar_loss = [], []
    for lam in lambdas:
        sched = solve_stochastic(frontier_scen, BATTERY, alpha=alpha, lambda_=lam, rho=frho)
        exp_profit.append(sched.expected_profit)
        cvar_loss.append(sched.cvar)

    # VSS curve: sweep the recourse budget ρ (risk-neutral).
    vss = [value_of_stochastic_solution(vss_scen, BATTERY, rho=r).vss for r in rhos]

    print(f"Risk-return frontier (α={alpha}, ρ={frho})\n")
    print(f"{'lambda':>8} {'E[profit]':>12} {'CVaR loss':>12}")
    print("-" * 34)
    for lam, e, c in zip(lambdas, exp_profit, cvar_loss, strict=True):
        print(f"{lam:>8.2f} {e:>12.3f} {c:>12.3f}")

    print("\nVSS vs recourse budget ρ (risk-neutral)\n")
    print(f"{'rho':>8} {'VSS':>12}")
    print("-" * 22)
    for r, v in zip(rhos, vss, strict=True):
        print(f"{r:>8.2f} {v:>12.3f}")

    from bess.viz.stochastic_plots import plot_risk_return_frontier, plot_vss_curve

    # The `tag` goes into the titles so each committed figure states its own
    # provenance. Without it a real-data figure and its synthetic fallback are
    # visually indistinguishable, and a README claiming "real" can go stale
    # invisibly — which is exactly what happened to these two.
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    f1 = plot_risk_return_frontier(
        exp_profit, cvar_loss, lambdas, title=f"Risk-return frontier (mean-CVaR) — {tag}"
    )
    p1 = FIG_DIR / "example-risk-return-frontier.svg"
    f1.savefig(p1, format="svg", bbox_inches="tight")
    f2 = plot_vss_curve(
        rhos, vss, title=f"Value of the stochastic solution vs recourse budget — {tag}"
    )
    p2 = FIG_DIR / "example-vss-curve.svg"
    f2.savefig(p2, format="svg", bbox_inches="tight")
    print(f"\nwrote {p1.name} and {p2.name} to docs/figures/ ({tag})")


if __name__ == "__main__":
    main()
