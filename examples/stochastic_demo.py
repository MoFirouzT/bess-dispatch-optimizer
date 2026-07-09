#!/usr/bin/env python3
"""Stochastic layer demo (R2.3) — the risk-return frontier and the VSS curve.

Builds a synthetic day-ahead scenario set (a common cheap charge hour, a random
later peak), then:

- sweeps the risk weight λ to trace the mean-CVaR frontier (expected profit vs
  downside), and
- sweeps the recourse budget ρ to show the value of the stochastic solution rise
  from 0 (no recourse) to a positive interior and back toward 0 (unlimited
  recourse) — the escape from the VSS = 0 trap.

Synthetic data only (the no-committed-data rule); numbers are illustrative, not a
gate. Run:

    uv run python examples/stochastic_demo.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from bess.assets.battery import BatterySpec
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


def main() -> None:
    # Risk-return frontier: sweep λ on the gamble set (at a fixed budget).
    frontier_scen = _frontier_scenarios()
    exp_profit, cvar_loss = [], []
    for lam in LAMBDAS:
        sched = solve_stochastic(
            frontier_scen, BATTERY, alpha=FRONTIER_ALPHA, lambda_=lam, rho=FRONTIER_RHO
        )
        exp_profit.append(sched.expected_profit)
        cvar_loss.append(sched.cvar)

    # VSS curve: sweep the recourse budget ρ on the random-peak set (risk-neutral).
    vss_scen = _vss_scenarios()
    vss = [value_of_stochastic_solution(vss_scen, BATTERY, rho=r).vss for r in RHOS]

    print(f"Risk-return frontier (α={FRONTIER_ALPHA}, ρ={FRONTIER_RHO})\n")
    print(f"{'lambda':>8} {'E[profit]':>12} {'CVaR loss':>12}")
    print("-" * 34)
    for lam, e, c in zip(LAMBDAS, exp_profit, cvar_loss, strict=True):
        print(f"{lam:>8.2f} {e:>12.3f} {c:>12.3f}")

    print("\nVSS vs recourse budget ρ (risk-neutral)\n")
    print(f"{'rho':>8} {'VSS':>12}")
    print("-" * 22)
    for r, v in zip(RHOS, vss, strict=True):
        print(f"{r:>8.2f} {v:>12.3f}")

    from bess.viz.stochastic_plots import plot_risk_return_frontier, plot_vss_curve

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    f1 = plot_risk_return_frontier(exp_profit, cvar_loss, LAMBDAS)
    p1 = FIG_DIR / "example-risk-return-frontier.svg"
    f1.savefig(p1, format="svg", bbox_inches="tight")
    f2 = plot_vss_curve(RHOS, vss)
    p2 = FIG_DIR / "example-vss-curve.svg"
    f2.savefig(p2, format="svg", bbox_inches="tight")
    print(f"\nwrote {p1.name} and {p2.name} to docs/figures/")


if __name__ == "__main__":
    main()
