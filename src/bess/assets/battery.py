"""Battery asset — config (``BatterySpec`` / ``DegradationSpec``) + the plugin that
registers the R1.1/R1.2 formulation onto a Pyomo model.

Formulation: ``docs/formulation.md`` §§ "R1.1 — Deterministic core" and "R1.2.
Degradation cost". All power is **grid-side**; efficiency
appears **only** in the SoC balance (R1.1) and in the cell-side throughput that
drives degradation (R1.2), never in the objective's cash flow (owned by
``optimizer.core``).
"""

from __future__ import annotations

from collections.abc import Sequence

import pyomo.environ as pyo
from pydantic import BaseModel, Field, model_validator


class DegradationSpec(BaseModel):
    """Linear degradation cost on per-period storage-side throughput.

    ``cost_per_mwh`` is the single marginal wear cost c_deg (€/MWh of storage-side
    throughput): D_t = c_deg · τ_t (formulation §R1.2, the linear power-based case of
    the Xu 2018 / Shi 2017 cycle-based aging model). Grounded values sit near
    €7–15/MWh (cell replacement cost ÷ lifetime throughput). c_deg = 0 reduces to R1.1.
    """

    cost_per_mwh: float = Field(ge=0.0)  # c_deg (€/MWh storage-side throughput)

    model_config = {"frozen": True, "extra": "forbid"}


class BatterySpec(BaseModel):
    """Physical + operating spec for a battery.

    Units: power MW, `capacity` MWh, efficiency per-unit. SoC fields
    (`soc_min` / `soc_initial` / `soc_terminal`) are **per-unit** fractions of
    `capacity` (size-independent config; see conventions §2 and ADR-0009) — the
    asset converts them to absolute MWh at registration. Defaults match the R1.1
    sanity band — a 1 MWh / 1 MW (1-hour, 1C) asset.
    """

    capacity: float = Field(default=1.0, gt=0)  # e_max (MWh)
    soc_min: float = Field(default=0.0, ge=0, le=1)  # e_min / e_max (per-unit)
    p_charge_max: float = Field(default=1.0, gt=0)  # P̄_ch (MW)
    p_discharge_max: float = Field(default=1.0, gt=0)  # P̄_dis (MW)
    eta_charge: float = Field(default=0.95, gt=0, le=1)  # η_ch ∈ (0, 1]
    eta_discharge: float = Field(default=0.95, gt=0, le=1)  # η_dis ∈ (0, 1]
    ramp: float | None = Field(default=None, gt=0)  # R (MW/period); None disables
    soc_initial: float = Field(default=0.0, ge=0, le=1)  # e_0 / e_max (per-unit)
    soc_terminal: float = Field(default=0.0, ge=0, le=1)  # e_tgt / e_max (per-unit)
    degradation: DegradationSpec | None = Field(default=None)  # None ⇒ R1.1 behavior

    model_config = {"frozen": True, "extra": "forbid"}

    @model_validator(mode="after")
    def _check_soc_window(self) -> BatterySpec:
        # Per-unit SoC: the usable window is [soc_min, 1.0] (1.0 == full capacity).
        if self.soc_min >= 1.0:
            raise ValueError(f"soc_min ({self.soc_min}) must be < 1.0 (the full-capacity bound)")
        for name, v in (("soc_initial", self.soc_initial), ("soc_terminal", self.soc_terminal)):
            if not self.soc_min <= v <= 1.0:
                raise ValueError(
                    f"{name} ({v}) must lie in [soc_min, 1.0] = [{self.soc_min}, 1.0] (per-unit)"
                )
        return self


class Battery:
    """Plugin asset: registers its variables and constraints onto a Pyomo model.

    Single-asset R1.1 attaches components directly to the model. Multi-asset
    co-optimization (future) would namespace these under a Pyomo ``Block``.
    """

    def __init__(self, spec: BatterySpec):
        self.spec = spec

    def register(self, model: pyo.ConcreteModel, prices: Sequence[float], dt: float) -> None:
        s = self.spec
        n = len(prices)

        # Convert per-unit SoC config to absolute MWh (the model works in MWh).
        e_max = s.capacity
        e_min = s.soc_min * s.capacity
        e_initial = s.soc_initial * s.capacity
        e_terminal = s.soc_terminal * s.capacity

        model.T = pyo.RangeSet(0, n - 1)  # periods 0..T-1; e_0 = e_initial

        # Decision variables. Power is grid-side and non-negative; u_t = charge flag.
        model.p_charge = pyo.Var(model.T, domain=pyo.NonNegativeReals)
        model.p_discharge = pyo.Var(model.T, domain=pyo.NonNegativeReals)
        # (2) SoC bounds enforced as variable bounds (absolute MWh).
        model.soc = pyo.Var(model.T, domain=pyo.Reals, bounds=(e_min, e_max))
        model.u = pyo.Var(model.T, domain=pyo.Binary)

        # (1) SoC balance — efficiency lives HERE (grid-side metering), never in the objective.
        def _soc_balance(m, t):
            prev = e_initial if t == 0 else m.soc[t - 1]
            return m.soc[t] == (
                prev + s.eta_charge * m.p_charge[t] * dt - (m.p_discharge[t] / s.eta_discharge) * dt
            )

        model.soc_balance = pyo.Constraint(model.T, rule=_soc_balance)

        # (3) Power limits with mutual exclusion — big-M is the power cap itself.
        model.charge_limit = pyo.Constraint(
            model.T, rule=lambda m, t: m.p_charge[t] <= s.p_charge_max * m.u[t]
        )
        model.discharge_limit = pyo.Constraint(
            model.T, rule=lambda m, t: m.p_discharge[t] <= s.p_discharge_max * (1 - m.u[t])
        )

        # (4) Ramp on net power (optional; None disables).
        if s.ramp is not None:
            ramp_limit = s.ramp  # MW/period

            def _ramp(m, t):
                if t == 0:
                    return pyo.Constraint.Skip
                net_t = m.p_discharge[t] - m.p_charge[t]
                net_prev = m.p_discharge[t - 1] - m.p_charge[t - 1]
                return (-ramp_limit, net_t - net_prev, ramp_limit)

            model.ramp_limit = pyo.Constraint(model.T, rule=_ramp)

        # (5) Terminal SoC.
        model.terminal_soc = pyo.Constraint(expr=model.soc[n - 1] == e_terminal)

        # R1.2 — linear degradation cost D_t = c_deg · τ_t on storage-side throughput.
        # A Pyomo Expression (not a Var), so it is native to the LP: no auxiliary cuts,
        # variables, or breakpoints. Absent when no degradation ⇒ model is R1.1 exactly.
        if s.degradation is not None:
            c_deg = s.degradation.cost_per_mwh

            def _degradation_cost(m, t):  # τ_t is storage-side, both directions
                tau = s.eta_charge * m.p_charge[t] * dt + (m.p_discharge[t] / s.eta_discharge) * dt
                return c_deg * tau

            model.degradation_cost = pyo.Expression(model.T, rule=_degradation_cost)


def schedule_degradation_cost(
    spec: BatterySpec,
    p_charge: Sequence[float],
    p_discharge: Sequence[float],
    dt: float,
) -> float:
    """Total linear degradation cost Σ D_t = c_deg · Σ τ_t of a *given* dispatch (0 if no spec).

    Mirrors the MILP's per-period ``D_t = c_deg · τ_t`` (formulation §R1.2) so a
    heuristic schedule is scored net of degradation on the same basis as a solver
    schedule; this is what keeps ``V_greedy ≤ V_roll`` valid once wear is priced.
    """
    deg = spec.degradation
    if deg is None:
        return 0.0
    return deg.cost_per_mwh * sum(
        spec.eta_charge * pc * dt + pd_ / spec.eta_discharge * dt
        for pc, pd_ in zip(p_charge, p_discharge, strict=True)
    )
