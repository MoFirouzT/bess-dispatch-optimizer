"""Value of the stochastic solution and EVPI (R2.3).

Formulation: ``docs/formulation.md`` § R2.3 (Birge-Louveaux). Reports the
decision-value metrics that make the stochastic layer *measured*, not asserted:

- **EV**  — the mean-value solve at ``π̄``;
- **RP**  — the risk-neutral two-stage optimum (recourse problem);
- **EEV** — the mean-value first stage evaluated with optimal recourse;
- **WS**  — wait-and-see, the scenario-averaged perfect-foresight value
  (= R1.4's ceiling averaged over scenarios);
- **VSS** ``= RP − EEV ≥ 0``;  **EVPI** ``= WS − RP ≥ 0``, with ``EEV ≤ RP ≤ WS``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from bess.assets.battery import BatterySpec
from bess.optimizer.core import solve
from bess.stochastic.twostage import solve_stochastic

if TYPE_CHECKING:
    from bess.scenarios import ScenarioSet


@dataclass
class VSSResult:
    """The R2.3 decision-value metrics (all EUR)."""

    ev: float
    rp: float
    eev: float
    ws: float
    vss: float  # RP − EEV
    evpi: float  # WS − RP


def value_of_stochastic_solution(
    scenarios: ScenarioSet,
    battery: BatterySpec,
    *,
    dt: float = 1.0,
    rho: float = 0.5,
    alpha: float = 0.95,
) -> VSSResult:
    """Compute EV / RP / EEV / WS and the derived VSS, EVPI over ``scenarios``.

    The metrics are risk-neutral (``lambda_=0``); ``alpha`` is carried only so the
    CVaR auxiliaries are well-posed and does not affect the reported values.
    """
    paths = np.asarray(scenarios.paths, dtype=float)
    probs = np.asarray(scenarios.probs, dtype=float)
    s_n = paths.shape[0]
    mean_path = probs @ paths

    ev_sched = solve(list(mean_path), battery, dt)
    ev = ev_sched.objective

    rp = solve_stochastic(
        scenarios, battery, dt=dt, alpha=alpha, lambda_=0.0, rho=rho
    ).expected_profit
    eev = solve_stochastic(
        scenarios,
        battery,
        dt=dt,
        alpha=alpha,
        lambda_=0.0,
        rho=rho,
        fix_da=(ev_sched.p_charge, ev_sched.p_discharge),
    ).expected_profit
    ws = float(sum(probs[s] * solve(list(paths[s]), battery, dt).objective for s in range(s_n)))

    return VSSResult(ev=ev, rp=rp, eev=eev, ws=ws, vss=rp - eev, evpi=ws - rp)


@dataclass
class OutOfSampleVSS:
    """Out-of-sample decision-value metrics (all EUR; ADR-0021).

    ``rp_oos`` / ``eev_oos`` are the *held-out* expected profits of the RP and EV
    first-stage commitments (fit on the training scenarios), evaluated with optimal
    within-budget recourse on disjoint realised paths; ``vss_oos = rp_oos − eev_oos``.
    """

    rp_oos: float
    eev_oos: float
    vss_oos: float


def _net_to_pair(g: list[float]) -> tuple[list[float], list[float]]:
    """Split a net-export schedule into (p_charge, p_discharge) under mutual exclusion."""
    return [max(-x, 0.0) for x in g], [max(x, 0.0) for x in g]


def out_of_sample_vss(
    train: ScenarioSet,
    evaluation: ScenarioSet,
    battery: BatterySpec,
    *,
    dt: float = 1.0,
    rho: float = 0.5,
    alpha: float = 0.95,
) -> OutOfSampleVSS:
    """Fit the commitments on ``train``, score them on held-out ``evaluation`` paths.

    The honest VSS ([ADR-0021](../decisions/0021-mpc-recourse-out-of-sample-vss.md)):
    the RP and EV first-stage decisions are fit on the training scenarios, then each
    is *fixed* and evaluated with optimal within-budget recourse on the disjoint
    evaluation realisations. The day-ahead leg settles at the training price for
    both, so the comparison isolates the commitment quality. Unlike the in-sample
    VSS this is not guaranteed non-negative; a positive value is genuine
    generalisation of the stochastic plan.
    """
    train_paths = np.asarray(train.paths, dtype=float)
    train_probs = np.asarray(train.probs, dtype=float)
    train_mean = train_probs @ train_paths

    # Fit both first-stage commitments on the training set.
    ev_sched = solve(list(train_mean), battery, dt)
    ev_pair = (ev_sched.p_charge, ev_sched.p_discharge)
    rp_sched = solve_stochastic(train, battery, dt=dt, alpha=alpha, lambda_=0.0, rho=rho)
    rp_pair = _net_to_pair(rp_sched.g_da)

    # Score each fixed commitment on the held-out paths at the training DA price.
    def score(pair: tuple[list[float], list[float]]) -> float:
        return solve_stochastic(
            evaluation,
            battery,
            dt=dt,
            alpha=alpha,
            lambda_=0.0,
            rho=rho,
            fix_da=pair,
            pi_da=train_mean,
        ).expected_profit

    rp_oos = score(rp_pair)
    eev_oos = score(ev_pair)
    return OutOfSampleVSS(rp_oos=rp_oos, eev_oos=eev_oos, vss_oos=rp_oos - eev_oos)
