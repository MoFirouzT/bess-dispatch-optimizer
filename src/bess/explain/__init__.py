"""explain — shadow-price / dual explainability (R2.4).

Reads the SoC-balance dual (the marginal water value of stored energy) off the solved
R1.1/R1.2 dispatch by fix-and-resolve. Imported by ``api``; imports ``optimizer`` and
``assets`` only (it does not explain the R2.3 stochastic program;
docs/decisions/milp-dual-resolve-rule.md, decision 3).
"""

from bess.explain.duals import (
    DualityError,
    Explanation,
    FlatRun,
    PeriodExplanation,
    explain_schedule,
)

__all__ = [
    "DualityError",
    "Explanation",
    "FlatRun",
    "PeriodExplanation",
    "explain_schedule",
]
