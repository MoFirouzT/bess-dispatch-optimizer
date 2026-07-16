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


class RunOut(BaseModel):
    """A flat run of periods sharing one water value (R2.4)."""

    periods: list[int]
    water_value_eur_mwh: float
    pinned: bool


class PeriodOut(BaseModel):
    """Per-period explanation. Band edges and breakeven are null where not defined
    (band on an unpinned run; breakeven at an idle period)."""

    action: str  # "charge" | "discharge" | "idle"
    price_eur_mwh: float
    water_value_eur_mwh: float
    degradation_cost_eur: float
    run: int
    reason: str
    band_low_eur_mwh: float | None
    band_high_eur_mwh: float | None
    breakeven_slippage_eur_mwh: float | None


class ExplainResponse(BaseModel):
    """Dispatch schedule plus its shadow-price explanation (R2.4). No fallback mode:
    the endpoint carries no circuit breaker, so a schedule here is always optimal."""

    objective_eur: float
    schedule: ScheduleOut
    runs: list[RunOut]
    periods: list[PeriodOut]


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
