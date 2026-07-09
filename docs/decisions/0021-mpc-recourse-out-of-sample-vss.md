# ADR-0021: Recourse is a receding-horizon MPC policy; VSS is measured out-of-sample

**Status:** Accepted
**Date:** 2026-07-09
**Supersedes / Superseded by:** none (implements [ADR-0007](0007-stochastic-value-requires-risk-or-recourse.md) with [ADR-0019](0019-day-ahead-intraday-two-stage.md))

## Context

[ADR-0019](0019-day-ahead-intraday-two-stage.md) fixes the two-stage *decision* structure. Two things still need deciding: how the recourse is *realized operationally* (the deployable intraday policy), and how VSS/EEV/WS are *estimated* so the reported value is honest rather than an in-sample artefact of the very scenarios the decision was fit to.

## Decision

Realize the recourse as a **receding-horizon (MPC) policy**: execute the committed action for the current window, then re-solve the remaining horizon at the updated realized prices, carrying SoC as the linking state, warm-started from the previous window's solution. Estimate the decision-value metrics (EV, RP, EEV, WS, VSS = RP − EEV, EVPI = WS − RP) **out-of-sample**: fit the first-stage decision on a reduced scenario set, then evaluate on *disjoint* realized paths under R1.4 walk-forward / leakage discipline.

## Rationale

- **MPC is the honest name for intraday re-optimization.** A plant model (SoC balance), state continuity across windows, a re-optimization trigger per period, and price forecasts as the disturbance is exactly receding-horizon control; naming it so is sharper than "intraday re-solve" and reuses the R1.1 model per window.
- **Warm-start is justified by latency, not pedigree.** Each re-solve is a small perturbation of the last; seeding it cuts solve time, the one concrete optimization the recourse loop needs.
- **Granularity is already supported.** `dt` is a per-solve argument, so intraday windows can refine to 15-minute while day-ahead stays hourly without a model change ([ADR-0006](0006-day-ahead-15min-native.md)).
- **Out-of-sample is the only honest VSS.** Evaluating on the fitting scenarios inflates VSS (the decision has seen the futures it is scored against). Held-out realized paths under the R1.4 information-set discipline make the reported number a generalization estimate, consistent with how the deterministic backtest already reports value.

## Consequences

- The recourse simulator lives in `bess.recourse` (imports `bess.optimizer` only); the two-stage planner and metric harness live in `bess.stochastic` (imports `scenarios`, `recourse`, `optimizer`). Both fill already-declared import-linter layers.
- The gate compares the stochastic-planned policy against the mean-planned policy on the same held-out paths; a non-positive out-of-sample VSS indicts the construction and is surfaced, not suppressed.
- WS on the evaluation paths is the R1.4 perfect-foresight ceiling, so the deterministic and stochastic gates share one ceiling definition.

## Failure mode

VSS is positive in-sample but ≈ 0 (or negative) out-of-sample, meaning the stochastic plan overfit the fitting scenarios. Signal: the in-sample/out-of-sample VSS gap is large. Mitigation: the gate is the out-of-sample number; the in-sample value is reported only as a diagnostic alongside it.

## Alternatives considered

- **A single two-stage solve with no rolling deployment.** Sufficient to *define* VSS, but it does not demonstrate the deployable intraday policy the master plan calls for; the MPC loop is what makes the recourse operational and handles granularity.
- **In-sample VSS on the fitting scenarios.** Simpler and always non-negative, but optimistically biased; rejected as the reported metric, kept only as a diagnostic.
- **Perfect-foresight recourse as the policy.** That is WS (the ceiling), not a deployable policy; it bounds VSS from above via EVPI but cannot be executed.
