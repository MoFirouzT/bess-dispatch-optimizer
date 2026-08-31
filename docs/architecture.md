# Architecture

How the project is organized, the module layering, the documentation tiers, and the order to read things in.
For the math itself see [formulation.md](formulation.md);
for the locked conventions (units, sign, time, naming) see [conventions.md](conventions.md).

*Assumes:
the component vocabulary in the [glossary](glossary.md).
this file maps the system's layers to the code's packages and points to [formulation](formulation.md) for the math.*

---

## What the system does

The optimizer takes a **day-ahead price curve** and a **battery spec** (power, energy, efficiency, ramp, SoC window) and returns the revenue-maximizing charge/discharge schedule, formulated as a deterministic MILP and solved with HiGHS.
On top of that sit the uncertainty capabilities:
a conformal price forecaster conditioned on residual load and watched by a drift monitor, scenario generation with an extreme-value tail, risk-aware two-stage optimization with intraday recourse, and dual-based explainability.
All eight capabilities are complete and gated.

The `R<n>.<m>` phase IDs used across `docs/specs/` are delivery labels, not architecture.
The map between them and the capabilities below is in the [phase ledger](specs/README.md).

---

## Reading order

1. [README](../README.md): what the project is and why.
2. **This file**: the map.
3. [formulation.md](formulation.md): the math. Start at *Conventions* (the grid-side metering rule), then the deterministic core. Uncertainty and evaluation are in its two companion files, [formulation-uncertainty.md](formulation-uncertainty.md) and [formulation-evaluation.md](formulation-evaluation.md).
4. [conventions.md](conventions.md): units, sign/metering, time, naming. Locked; changes need an ADR.
5. [glossary.md](glossary.md) and [market_reference.md](market_reference.md): domain background, read as needed.
6. [studies/](studies/): what the stack was measured to be worth, nulls included.
7. [specs/&lt;phase&gt;.md](specs/): the frozen work order for a given phase, with its test contract.

One source of truth per fact:
the specs, the README, and the [ADRs](decisions/) point to the formulation; they never restate an equation.

---

## Module layering

The `bess` package is split into layers with a strict import direction, enforced in CI by [import-linter](https://github.com/seddonym/import-linter).
Imports point **downward only**: a lower layer never imports a higher one.

```text
api → narrate → explain → stochastic → recourse → optimizer → validation → assets
                                 ▲
          forecaster → scenarios ┘
```

| Layer | Responsibility |
| --- | --- |
| `assets` | Physical battery model: `BatterySpec`, the SoC balance and physics constraints it registers on a Pyomo model. |
| `validation` | Pre-flight feasibility checks; structured, typed errors before the solver runs. |
| `optimizer` | Builds the objective, owns the solve, returns a `Schedule`. The deterministic core. It also owns the greedy heuristic, which lives here rather than in `backtest` so the serving breaker can reuse it without the serving chain depending on the offline harness. |
| `recourse` | Rolling-horizon / MPC re-optimization. |
| `stochastic` | The risk-aware two-stage program: scenario-based optimization and its decision-value metrics. |
| `explain` | Shadow prices and dispatch explanations. Offline and deterministic. |
| `narrate` | Prose accounts of an `explain` result. The only layer that reaches a language model, and it sits above `explain` so that layer stays offline. Every quantity is substituted here from the solved model, never written by the model, and an unverifiable narration is replaced by a deterministic one. |
| `api` | The serving entry point. |
| `forecaster` | Probabilistic price forecasting (conformal intervals), day-ahead fundamentals features, a forecast-drift monitor, and the calibration machinery measured against it: a sharpness search over the learners and the drift-robust conformal constructions (weighted quantiles, adaptive levels). Neither of those two changed a shipped default. |
| `scenarios` | Scenario generation from forecasts, with an extreme-value / residual-load-conditional tail, feeding `stochastic`. |

Four packages sit deliberately **outside** the serving chain:

- `backtest`:
  an offline evaluation tool.
  It must not import the serving chain (`api`, `explain`, `stochastic`, `recourse`, `scenarios`, `forecaster`);
  it drives the optimizer directly.
- `studies`:
  the value studies that aggregate across many delivery windows.
  The import-linter contract runs the *other* way, because a study legitimately imports the chain it measures:
  nothing in the chain may import `studies`.
  That single forbidden edge is what makes "studies are not the product" a mechanical fact rather than a claim.

  **The dividing line, stated as a rule for future work:**
  a function that *aggregates over windows* is a study;
  a function that reports on a *single scenario set* is part of the program.
  That is why the Birge-Louveaux decision-value metrics stay in `bess.stochastic` while the multi-window harnesses moved out.
- `data`:
  the ENTSO-E loaders (day-ahead prices; day-ahead load and wind/solar forecasts) and the ingestion guard that wraps the fetch.
  A leaf: it imports nothing else in `bess`.
- `viz`:
  the plotting code that regenerates the figures in `docs/figures/`.
  It reads results from the layers it plots and nothing imports it, so it carries no import-linter contract.
  matplotlib is an optional extra, not a runtime dependency.

The headline invariant is `optimizer ⊥ api` (the optimizer never depends on the serving layer), which the layered contract gives for free.

---

## Two circuit breakers

Two circuit breakers live at **different layers** and must stay separate (see [two separate circuit breakers](decisions/separate-ingestion-breaker.md)):
the **ingestion** breaker guards the *fetch* in the `data` leaf, and the **solver** breaker guards the *solve* in `api`.
The ingestion guard is a data-layer reliability piece, not part of serving.

---

## Solver & stack

- **Modeling:**
  [Pyomo](https://www.pyomo.org/), which builds the MILP.
- **Solver:**
  [HiGHS](https://highs.dev/) via `highspy` / Pyomo's `appsi_highs`.
  Degradation is a **linear** wear cost (the linear depth-of-discharge stress case of Xu 2018 / Shi 2017; see [formulation.md: R1.2](formulation.md#r12-degradation-cost)), native to the LP.
  A future nonlinear-convex degradation would use the epigraph form rather than SOS2, since HiGHS has no native SOS support.
- **Config:**
  [Pydantic v2](https://docs.pydantic.dev/), typed model parameters from YAML, validated at startup.
- **Time series:**
  `pandas`, tz-aware UTC index (see [conventions.md: Time](conventions.md#1-time)).
