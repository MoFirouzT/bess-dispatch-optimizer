"""Pre-flight validation — structured, typed checks that run *before* the solver.

Formulation: ``docs/formulation.md`` § "R1.3 — Pre-flight feasibility (derived; no
new model)". Spec: ``docs/specs/R1.3-validation.md``.

Pure logic over ``(prices, BatterySpec, dt)`` — no config, no I/O, no solver. The
spec is assumed already valid (Pydantic validates ``BatterySpec`` at construction),
so this layer only catches the **solve-time** failure class: dirty inputs and
**terminal-SoC unreachability** (``T = len(prices)`` is unknown until solve time).

``validate`` accumulates *all* issues and never raises; ``check`` raises
``PreflightError`` if any are found. This module imports ``assets`` only
(import-linter: ``optimizer → validation → assets``).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from bess.assets.battery import BatterySpec

# Boundary tolerance: an exactly-reachable target (required == reachable) must
# pass, so only flag when required exceeds reachable by more than float noise.
_REACH_TOL = 1e-9


class IssueCode(StrEnum):
    """Stable, machine-readable identifiers for each pre-flight failure mode."""

    EMPTY_HORIZON = "empty_horizon"
    NON_FINITE_PRICE = "non_finite_price"
    NON_POSITIVE_DT = "non_positive_dt"
    TERMINAL_UNREACHABLE_CHARGE = "terminal_unreachable_charge"
    TERMINAL_UNREACHABLE_DISCHARGE = "terminal_unreachable_discharge"


@dataclass(frozen=True)
class ValidationIssue:
    """One pre-flight finding. ``context`` carries the numbers behind ``message``."""

    code: IssueCode
    field: str  # which input: "prices", "prices[3]", "dt", "soc_terminal"
    message: str  # human-readable and actionable; embeds the numbers
    context: dict[str, float | int] = field(default_factory=dict)


class PreflightError(Exception):
    """Raised by ``check`` when ``validate`` finds one or more issues."""

    def __init__(self, issues: list[ValidationIssue]):
        self.issues = issues
        summary = "; ".join(f"[{i.code.value}] {i.message}" for i in issues)
        super().__init__(f"pre-flight validation failed: {summary}")


def validate(prices: Sequence[float], spec: BatterySpec, dt: float) -> list[ValidationIssue]:
    """Return ALL pre-flight issues (possibly empty). Pure; never raises, never solves.

    Order is fixed for determinism: ``dt`` hygiene, then ``prices`` left-to-right,
    then terminal reachability.
    """
    issues: list[ValidationIssue] = []

    # --- Input hygiene ------------------------------------------------------
    dt_ok = math.isfinite(dt) and dt > 0.0
    if not dt_ok:
        issues.append(
            ValidationIssue(
                code=IssueCode.NON_POSITIVE_DT,
                field="dt",
                message=f"dt must be a finite positive period length, got {dt!r}",
                context={"dt": dt},
            )
        )

    n = len(prices)
    if n == 0:
        issues.append(
            ValidationIssue(
                code=IssueCode.EMPTY_HORIZON,
                field="prices",
                message="prices is empty — no periods to dispatch",
            )
        )

    for t, p in enumerate(prices):
        if not math.isfinite(p):
            issues.append(
                ValidationIssue(
                    code=IssueCode.NON_FINITE_PRICE,
                    field=f"prices[{t}]",
                    message=f"price at period {t} is not finite: {p!r}",
                    context={"index": t},
                )
            )

    # --- Terminal reachability (needs a real horizon and a usable dt) -------
    # Ramp-free necessary-and-sufficient condition (formulation §R1.3); with ramp
    # it stays necessary, so a verdict here is always sound. Skip when dt/horizon
    # are unusable — the issues above already explain why.
    if dt_ok and n >= 1:
        issues.extend(_reachability_issues(spec, n, dt))

    return issues


def _reachability_issues(spec: BatterySpec, n: int, dt: float) -> list[ValidationIssue]:
    e_initial = spec.soc_initial * spec.capacity
    e_terminal = spec.soc_terminal * spec.capacity
    delta = e_terminal - e_initial  # MWh of SoC change required

    # Per-period SoC increment bounds (formulation §R1.3): grid-side power through
    # the efficiencies in the SoC balance.
    step_up = spec.eta_charge * spec.p_charge_max * dt  # Δ⁺
    step_down = spec.p_discharge_max * dt / spec.eta_discharge  # Δ⁻

    if delta > 0:
        reachable = n * step_up
        if delta > reachable + _REACH_TOL:
            return [
                ValidationIssue(
                    code=IssueCode.TERMINAL_UNREACHABLE_CHARGE,
                    field="soc_terminal",
                    message=(
                        f"terminal SoC needs +{delta:.6g} MWh of charging but at most "
                        f"{reachable:.6g} MWh is reachable in {n} period(s) "
                        f"(eta_ch*P_ch*dt = {step_up:.6g} per period)"
                    ),
                    context={
                        "required": delta,
                        "reachable": reachable,
                        "horizon": n,
                        "dt": dt,
                    },
                )
            ]
    elif delta < 0:
        required = -delta
        reachable = n * step_down
        if required > reachable + _REACH_TOL:
            return [
                ValidationIssue(
                    code=IssueCode.TERMINAL_UNREACHABLE_DISCHARGE,
                    field="soc_terminal",
                    message=(
                        f"terminal SoC needs -{required:.6g} MWh of discharging but at most "
                        f"{reachable:.6g} MWh is reachable in {n} period(s) "
                        f"(P_dis*dt/eta_dis = {step_down:.6g} per period)"
                    ),
                    context={
                        "required": required,
                        "reachable": reachable,
                        "horizon": n,
                        "dt": dt,
                    },
                )
            ]
    return []


def check(prices: Sequence[float], spec: BatterySpec, dt: float) -> None:
    """Raise ``PreflightError`` if ``validate`` finds any issue; else return ``None``."""
    issues = validate(prices, spec, dt)
    if issues:
        raise PreflightError(issues)
