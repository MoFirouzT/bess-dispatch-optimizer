# Architecture

How the project is organized, the module layering, the documentation tiers, and the order to read things in. For the math itself see [formulation.md](formulation.md); for the locked conventions (units, sign, time, naming) see [conventions.md](conventions.md).

*Assumes: familiarity with Python packaging and MILP basics. Battery and power-market terms are defined in the [glossary](glossary.md).*

---

## What the system does

The optimizer takes a **day-ahead price curve** and a **battery spec** (power, energy, efficiency, ramp, SoC window) and returns the revenue-maximizing charge/discharge schedule, formulated as a deterministic MILP and solved with HiGHS. Release 1 builds this deterministic core and a leakage-safe backtest around it; Release 2 (planned) adds price forecasting, scenario generation, stochastic/recourse optimization, and explainability.

---

## Reading order

1. [README](../README.md): what the project is and why.
2. **This file**: the map.
3. [formulation.md](formulation.md): the math. Start at *Conventions* (the grid-side metering rule), then R1.1.
4. [conventions.md](conventions.md): units, sign/metering, time, naming. Locked; changes need an ADR.
5. [glossary.md](glossary.md) and [market_reference.md](market_reference.md): domain background, read as needed.
6. [specs/&lt;phase&gt;.md](specs/): the frozen work order for a given phase, with its test contract.

---

## Module layering

The `bess` package is split into layers with a strict import direction, enforced in CI by [import-linter](https://github.com/seddonym/import-linter). Imports point **downward only**: a lower layer never imports a higher one.

```
api → explain → stochastic → recourse → optimizer → validation → assets
                   ▲
    forecaster → scenarios ┘
```

| Layer | Responsibility |
|---|---|
| `assets` | Physical battery model: `BatterySpec`, the SoC balance and physics constraints it registers on a Pyomo model. |
| `validation` | Pre-flight feasibility checks (R1.3); structured, typed errors before the solver runs. |
| `optimizer` | Builds the objective, owns the solve, returns a `Schedule`. The deterministic core (R1.1/R1.2). |
| `recourse` | Rolling-horizon / MPC re-optimization (R2, planned). |
| `stochastic` | Scenario-based and risk-aware optimization (R2, planned). |
| `explain` | Shadow prices and dispatch explanations (R2, planned). |
| `api` | The serving entry point. |
| `forecaster` → `scenarios` | Price forecasting and scenario generation, feeding `stochastic` (R2, planned). |

Two layers sit deliberately **outside** the serving chain:

- `backtest`: an offline evaluation tool (R1.4). It must not import the serving chain (`api`, `explain`, `stochastic`, `recourse`, `scenarios`, `forecaster`); it drives the optimizer directly.
- `data`: the ENTSO-E loader (R1.4b). A leaf: it imports nothing else in `bess`.

The headline invariant is `optimizer ⊥ api` (the optimizer never depends on the serving layer), which the layered contract gives for free.

---

## Documentation tiers

The doc set is layered by stability and purpose (the full rule is in [CLAUDE.md](../CLAUDE.md) §2):

- **Tier 1 (public face):** [README](../README.md), this file. Stable, minimal, project-only.
- **Tier 2 (canonical references):** [formulation.md](formulation.md) (the math), [glossary.md](glossary.md), [references.md](references.md), [decisions/](decisions/) (ADRs: the *why* behind locked choices).
- **Tier 3 (per-phase work orders):** [specs/](specs/). One per phase: scope, interfaces, and the golden/property test contract.
- **Tier 0 (`planning/`):** gitignored, never committed. The master plan lives here.

The governing rule: **one source of truth per fact.** Specs, the README, and ADRs *point to* the formulation; they never restate an equation.

---

## Solver & stack

- **Modeling:** [Pyomo](https://www.pyomo.org/), which builds the MILP.
- **Solver:** [HiGHS](https://highs.dev/) via `highspy` / Pyomo's `appsi_highs`. Note: HiGHS has no native SOS support, which is why R1.2's convex degradation cost uses the epigraph form rather than SOS2 (see [formulation.md § R1.2](formulation.md#r12--piecewise-linear-degradation-cost)).
- **Config:** [Pydantic v2](https://docs.pydantic.dev/), typed model parameters from YAML, validated at startup.
- **Time series:** `pandas`, tz-aware UTC index (see [conventions.md § Time](conventions.md#1-time)).
