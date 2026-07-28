"""studies — offline value studies over the dispatch stack (R2.5 / R2.5b / R2.6).

Each study answers a question *about* the pipeline and reports a finding; none of
them is on the serving path. The seam against ``bess.stochastic`` is deliberate:
a function that aggregates over windows is a study, a function that reports on a
single scenario set is part of the program, so the Birge-Louveaux metrics stay in
``bess.stochastic.vss`` while the multi-window harnesses live here.

Like ``bess.backtest`` this package sits outside the serving chain, and an
import-linter contract enforces the direction: studies may import the chain, and
nothing in the chain may import studies.

Spec: ``docs/specs/S1-capability-restructure.md``. No result is sign-asserted;
four of these studies returned nulls, which is reported as the finding.
"""

from __future__ import annotations

from bess.studies.bid_curve_value import (
    BidCurveValue,
    WindowBCV,
    bid_curve_value_across_windows,
    bid_curve_value_from_sets,
)
from bess.studies.forecast_value import (
    ForecastValue,
    WindowFV,
    forecast_value,
    forecast_value_from_sets,
    fv_across_windows,
    fv_windows_from_sets,
)
from bess.studies.tail_value import (
    TailValue,
    WindowTV,
    tail_value_across_windows,
    tail_value_from_sets,
)
from bess.studies.vss_study import WindowVSS, vss_across_windows
from bess.studies.windows import window_sets

__all__ = [
    "BidCurveValue",
    "ForecastValue",
    "TailValue",
    "WindowBCV",
    "WindowFV",
    "WindowTV",
    "WindowVSS",
    "bid_curve_value_across_windows",
    "bid_curve_value_from_sets",
    "forecast_value",
    "forecast_value_from_sets",
    "fv_across_windows",
    "fv_windows_from_sets",
    "tail_value_across_windows",
    "tail_value_from_sets",
    "vss_across_windows",
    "window_sets",
]
