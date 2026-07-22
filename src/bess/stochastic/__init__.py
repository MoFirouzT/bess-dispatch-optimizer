"""stochastic — risk-aware (CVaR mean-risk) two-stage dispatch + VSS reporting.

Formulation: ``docs/formulation.md`` § R2.3. Optimizes dispatch over a
``scenarios.ScenarioSet`` with a non-anticipative day-ahead commitment and
budget-limited intraday recourse, and measures the value of the stochastic
solution. Imports ``recourse`` / ``optimizer``; fed by ``forecaster`` /
``scenarios``. (R2.3)
"""

from __future__ import annotations

from bess.stochastic.risk import cvar_from_losses
from bess.stochastic.study import (
    ForecastValue,
    WindowVSS,
    forecast_value,
    forecast_value_from_sets,
    vss_across_windows,
    window_sets,
)
from bess.stochastic.twostage import StochasticSchedule, solve_stochastic
from bess.stochastic.vss import (
    OutOfSampleVSS,
    VSSResult,
    out_of_sample_vss,
    value_of_stochastic_solution,
)

__all__ = [
    "ForecastValue",
    "OutOfSampleVSS",
    "StochasticSchedule",
    "VSSResult",
    "WindowVSS",
    "cvar_from_losses",
    "forecast_value",
    "forecast_value_from_sets",
    "out_of_sample_vss",
    "solve_stochastic",
    "value_of_stochastic_solution",
    "vss_across_windows",
    "window_sets",
]
