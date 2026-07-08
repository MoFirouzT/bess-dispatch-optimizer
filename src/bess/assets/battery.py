"""Battery asset — config (``BatterySpec`` / ``DegradationSpec``) + the plugin that
registers the R1.1/R1.2 formulation onto a Pyomo model.

Formulation: ``docs/formulation.md`` §§ "R1.1 — Deterministic core" and "R1.2 —
Piecewise-linear degradation cost". All power is **grid-side**; efficiency
appears **only** in the SoC balance (R1.1) and in the cell-side throughput that
drives degradation (R1.2), never in the objective's cash flow (owned by
``optimizer.core``).
"""

from __future__ import annotations

from collections.abc import Sequence

import pyomo.environ as pyo
from pydantic import BaseModel, Field, model_validator


class DegradationSpec(BaseModel):
    """Convex piecewise-linear degradation cost on per-period storage-side throughput.

    Breakpoints are **per-unit of τ_max** (the max per-period throughput; see
    formulation §R1.2): ``throughput_pu`` runs 0 → 1, and ``cost_eur`` starts at 0
    and is **convex** (non-decreasing segment slopes). The model uses the epigraph
    form — no SOS2 — so convexity is required.
    """

    throughput_pu: list[float]  # φ_0=0 < ... < φ_K=1
    cost_eur: list[float]  # g_0=0 <= ... <= g_K, convex

    model_config = {"frozen": True, "extra": "forbid"}

    @model_validator(mode="after")
    def _check(self) -> DegradationSpec:
        phi, g = self.throughput_pu, self.cost_eur
        if len(phi) != len(g):
            raise ValueError("throughput_pu and cost_eur must have equal length")
        if len(phi) < 2:
            raise ValueError("need at least 2 breakpoints (>= 1 segment)")
        if phi[0] != 0.0 or phi[-1] != 1.0:
            raise ValueError("throughput_pu must start at 0.0 and end at 1.0 (per-unit of tau_max)")
        if g[0] != 0.0:
            raise ValueError("cost_eur must start at 0.0")
        if any(phi[k] <= phi[k - 1] for k in range(1, len(phi))):
            raise ValueError("throughput_pu must be strictly increasing")
        if any(g[k] < g[k - 1] for k in range(1, len(g))):
            raise ValueError("cost_eur must be non-decreasing")
        slopes = [(g[k] - g[k - 1]) / (phi[k] - phi[k - 1]) for k in range(1, len(phi))]
        # Magnitude-scaled tolerance: catch a real slope drop, ignore float noise.
        if any(
            slopes[k] < slopes[k - 1] - 1e-9 * max(1.0, abs(slopes[k - 1]))
            for k in range(1, len(slopes))
        ):
            raise ValueError("cost_eur must be convex (non-decreasing segment slopes)")
        return self

    def cost_at(self, tau_mwh: float, tau_max_mwh: float) -> float:
        """PWL degradation cost at storage-side throughput ``tau_mwh`` (MWh)."""
        if tau_max_mwh <= 0.0:
            return 0.0
        u = tau_mwh / tau_max_mwh  # per-unit of tau_max
        phi, g = self.throughput_pu, self.cost_eur
        if u <= phi[0]:
            return g[0]
        if u >= phi[-1]:
            return g[-1]
        for k in range(1, len(phi)):
            if u <= phi[k]:
                frac = (u - phi[k - 1]) / (phi[k] - phi[k - 1])
                return g[k - 1] + frac * (g[k] - g[k - 1])
        return g[-1]


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

        # R1.2 — convex PWL degradation cost via the epigraph form (no SOS2).
        # Skipped entirely when no degradation is configured ⇒ model is R1.1 exactly.
        if s.degradation is not None:
            deg = s.degradation
            window = e_max - e_min
            power_tau = max(
                s.eta_charge * s.p_charge_max * dt,
                s.p_discharge_max * dt / s.eta_discharge,
            )
            tau_max = min(power_tau, window)  # max per-period storage-side throughput

            # Absolute breakpoints and the affine segment lines a_k·τ + b_k.
            x = [phi * tau_max for phi in deg.throughput_pu]
            g = deg.cost_eur
            segments = []
            for k in range(1, len(x)):
                a = (g[k] - g[k - 1]) / (x[k] - x[k - 1])
                b = g[k - 1] - a * x[k - 1]
                segments.append((a, b))

            model.degradation_cost = pyo.Var(model.T, domain=pyo.NonNegativeReals)
            model.SEG = pyo.RangeSet(1, len(segments))

            def _throughput(m, t):  # storage-side, both directions
                return s.eta_charge * m.p_charge[t] * dt + (m.p_discharge[t] / s.eta_discharge) * dt

            # (6) Epigraph cuts: D_t >= a_k·τ_t + b_k. Convexity ⇒ minimizing D_t
            # drives it to the PWL value; no SOS/binaries needed.
            def _epigraph(m, t, k):
                a, b = segments[k - 1]
                return m.degradation_cost[t] >= a * _throughput(m, t) + b

            model.degradation_cut = pyo.Constraint(model.T, model.SEG, rule=_epigraph)
