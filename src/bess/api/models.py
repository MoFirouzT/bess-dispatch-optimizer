"""Pydantic request/response models for the dispatch service (R1.5).

The request reuses ``BatterySpec`` (Pydantic v2, the single source of truth for
asset parameters) directly, so model validation is identical to ``solve()``'s.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from bess.assets.battery import BatterySpec


class DispatchRequest(BaseModel):
    """One day-ahead dispatch request: a price curve, a step, and the asset."""

    prices_eur_mwh: list[float] = Field(description="Day-ahead price curve, grid-side, EUR/MWh.")
    dt_hours: float = Field(default=1.0, description="Period length in hours (> 0).")
    battery: BatterySpec


class ScheduleOut(BaseModel):
    """The served schedule, length T, grid-side power and MWh state of charge."""

    p_charge_mw: list[float]
    p_discharge_mw: list[float]
    soc_mwh: list[float]


class DispatchResponse(BaseModel):
    """Dispatch result. ``mode`` distinguishes the optimal solve from the fallback."""

    mode: str  # "optimal" | "fallback_greedy"
    objective_eur: float
    schedule: ScheduleOut
    solve_seconds: float
    solver_termination: str  # "optimal" | "fallback"


class IssueOut(BaseModel):
    """One structured pre-flight issue (conventions §6: typed errors, no raw traces)."""

    code: str
    field: str
    message: str
    context: dict[str, float | int]


class IssuesResponse(BaseModel):
    """422 body: every pre-flight issue found in an invalid request."""

    issues: list[IssueOut]


class HealthResponse(BaseModel):
    status: str
    solver: str
    solver_available: bool
