"""Per-window out-of-sample VSS: is VSS > 0 a market property or an instance one? (R2.5)

Formulation: ``docs/formulation-evaluation.md`` § R2.5; spec:
``docs/specs/value-evaluation.md``. Repeats the docs/decisions/risk-aware-two-stage-design.md
measurement over
arbitrary UTC-day windows of a real price series, so the reported object is a
*distribution* rather than a single number. Not sign-asserted: a negative window
is a finding, not a failure.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from bess.assets.battery import BatterySpec
from bess.stochastic.vss import out_of_sample_vss
from bess.studies.windows import window_sets


@dataclass(frozen=True)
class WindowVSS:
    """One window's out-of-sample decision-value result (EUR)."""

    window_start: pd.Timestamp
    rp_oos: float  # held-out score of the stochastic (RP) commitment
    eev_oos: float  # held-out score of the mean-value (EV) commitment
    # rp_oos − eev_oos; carries no sign guarantee, see
    # docs/decisions/risk-aware-two-stage-design.md
    vss_oos: float


def vss_across_windows(
    prices: pd.Series,
    battery: BatterySpec,
    *,
    history_days: int = 28,
    n_scenarios: int = 30,
    rho: float = 0.5,
    seed: int = 0,
) -> list[WindowVSS]:
    """The per-window out-of-sample VSS distribution (formulation §R2.5).

    Each window repeats the docs/decisions/risk-aware-two-stage-design.md protocol: fit the RP and
    EV commitments on
    the window's training scenarios, score each fixed (with optimal within-budget
    recourse, the day-ahead leg settling at the training mean) on the realized
    path. The caller reports the distribution; no single-number summary is
    computed here by design.
    """
    results: list[WindowVSS] = []
    for start, train, evaluation in window_sets(
        prices, history_days=history_days, n_scenarios=n_scenarios, seed=seed
    ):
        r = out_of_sample_vss(train, evaluation, battery, rho=rho)
        results.append(WindowVSS(start, r.rp_oos, r.eev_oos, r.vss_oos))
    return results
