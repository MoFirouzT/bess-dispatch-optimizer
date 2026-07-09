"""recourse — day-ahead commitment + intraday re-optimization (receding-horizon
MPC) with SoC continuity across windows. Imports ``optimizer``. (R2.3)
"""

from __future__ import annotations

from bess.recourse.mpc import RecourseResult, rolling_recourse

__all__ = ["RecourseResult", "rolling_recourse"]
