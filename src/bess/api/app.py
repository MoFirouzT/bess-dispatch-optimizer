"""FastAPI app for the dispatch service (R1.5, R2.4).

``POST /dispatch`` wraps ``solve()`` behind the circuit breaker
(``bess.api.service.dispatch``); ``POST /explain`` (R2.4) returns the same solve plus
its shadow-price explanation, **without** the breaker (decision 5); ``GET /health``
reports solver availability. Invalid input becomes a structured **422** (the pre-flight
issue list), never a raw solver trace (conventions §6). Operational knobs (latency
budget, greedy percentiles) are env-overridable settings with R1.5 defaults; model
parameters live in the request body.

Run: ``uvicorn bess.api.app:app``.
"""

from __future__ import annotations

import os

import pyomo.environ as pyo
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from bess.api.models import (
    DispatchRequest,
    DispatchResponse,
    ExplainResponse,
    HealthResponse,
    IssueOut,
    IssuesResponse,
    PeriodOut,
    RunOut,
    ScheduleOut,
)
from bess.api.service import dispatch
from bess.explain.duals import DualityError, explain_schedule
from bess.validation.preflight import PreflightError

SOLVER = "appsi_highs"


class Settings(BaseModel):
    """Operational settings (env-overridable). Not model parameters (conventions §5)."""

    latency_budget_seconds: float = 2.0
    greedy_charge_pct: float = 20.0
    greedy_discharge_pct: float = 80.0

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        return cls(
            latency_budget_seconds=float(env.get("BESS_LATENCY_BUDGET_S", 2.0)),
            greedy_charge_pct=float(env.get("BESS_GREEDY_CHARGE_PCT", 20.0)),
            greedy_discharge_pct=float(env.get("BESS_GREEDY_DISCHARGE_PCT", 80.0)),
        )


settings = Settings.from_env()
app = FastAPI(title="bess-dispatch-optimizer", version="1.0")


@app.exception_handler(PreflightError)
async def _preflight_handler(_request, exc: PreflightError) -> JSONResponse:
    """Map invalid / provably-infeasible input to a structured 422 (no fallback)."""
    body = IssuesResponse(
        issues=[
            IssueOut(
                code=str(i.code.value),
                field=i.input_field,
                message=i.message,
                context=dict(i.context),
            )
            for i in exc.issues
        ]
    )
    return JSONResponse(status_code=422, content=body.model_dump())


@app.post("/dispatch", response_model=DispatchResponse)
def post_dispatch(request: DispatchRequest) -> DispatchResponse:
    """Optimal dispatch, or the greedy fallback if the solver misses the latency budget."""
    result = dispatch(
        request.prices_eur_mwh,
        request.battery,
        request.dt_hours,
        budget=settings.latency_budget_seconds,
        charge_pct=settings.greedy_charge_pct,
        discharge_pct=settings.greedy_discharge_pct,
    )
    return DispatchResponse(
        mode=result.mode,
        objective_eur=result.objective,
        schedule=ScheduleOut(
            p_charge_mw=result.schedule.p_charge,
            p_discharge_mw=result.schedule.p_discharge,
            soc_mwh=result.schedule.soc,
        ),
        solve_seconds=result.solve_seconds,
        solver_termination=result.solver_termination,
    )


@app.post("/explain", response_model=ExplainResponse)
def post_explain(request: DispatchRequest) -> ExplainResponse:
    """Dispatch schedule plus its shadow-price explanation (R2.4, decision 5).

    Deliberately **not** behind the circuit breaker: the breaker's greedy fallback is
    a heuristic with no duals, so there is nothing to explain about it. Invalid input
    is a 422 (the shared pre-flight handler); a solve that does not reach optimality is
    a **503** (no faithful explanation), never a hollow 200 or a greedy schedule.
    """
    try:
        exp = explain_schedule(request.prices_eur_mwh, request.battery, dt=request.dt_hours)
    except DualityError as exc:  # a re-solve broke the invariant: an internal defect
        return JSONResponse(status_code=500, content={"detail": str(exc)})
    except RuntimeError as exc:  # solver missed optimality (e.g. ramp-coupled infeasible)
        return JSONResponse(status_code=503, content={"detail": str(exc)})
    return ExplainResponse(
        objective_eur=exp.schedule.objective,
        schedule=ScheduleOut(
            p_charge_mw=exp.schedule.p_charge,
            p_discharge_mw=exp.schedule.p_discharge,
            soc_mwh=exp.schedule.soc,
        ),
        runs=[
            RunOut(
                periods=list(r.periods),
                water_value_eur_mwh=r.water_value_eur_mwh,
                pinned=r.pinned,
            )
            for r in exp.runs
        ],
        periods=[
            PeriodOut(
                action=p.action,
                price_eur_mwh=p.price_eur_mwh,
                water_value_eur_mwh=p.water_value_eur_mwh,
                degradation_cost_eur=p.degradation_cost_eur,
                run=p.run,
                reason=p.reason,
                band_low_eur_mwh=p.band_low_eur_mwh,
                band_high_eur_mwh=p.band_high_eur_mwh,
                breakeven_slippage_eur_mwh=p.breakeven_slippage_eur_mwh,
            )
            for p in exp.periods
        ],
    )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness + solver availability (the CI Docker smoke target)."""
    available = bool(pyo.SolverFactory(SOLVER).available(exception_flag=False))
    return HealthResponse(status="ok", solver=SOLVER, solver_available=available)
