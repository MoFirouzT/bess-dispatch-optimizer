# The risk-aware two-stage design: structure, risk model, and how its value is measured

**Status:** Accepted
**Date:** 2026-07-09

*Consolidated on 2026-07-28 from three records made in one phase: the two-stage
construction, the choice of risk model, and the recourse policy plus estimation
protocol. Each was a short file, and together they are one design.*

Implements the requirement in
[stochastic value requires risk or recourse](stochastic-value-requires-risk-or-recourse.md).

## Context

The stochastic layer must provably escape the VSS = 0 trap. The trap is exact: with
the whole 24-hour dispatch as a single here-and-now decision, a risk-neutral linear
objective makes the stochastic solution equal to the mean-value solution
(`E_s[π^(s)·x] = π̄·x`), so VSS = 0.

A construction has to break that collapse while reusing the deterministic physics per
scenario, staying self-contained and testable without a token, and yielding a
hand-computable VSS for a golden oracle. Three things then need deciding: the
two-stage structure, the risk model, and how the reported value is estimated.

## Decision

### Structure

The **first stage** is a non-anticipative day-ahead net-export schedule `g^DA`, itself
feasible under the deterministic physics. The **second stage** is per-scenario
dispatch `g^(s)` at the realized price, tied to the commitment by a **recourse
budget** `|g^(s)_t − g^DA_t| ≤ ρ·P̄`, with `ρ ∈ [0,1]`. Day-ahead volume settles at a
known day-ahead price (default the scenario mean), the intraday deviation at the
realized price. The intraday signal is derived from the scenario set, so no new data
feed is introduced.

### Risk model

A **CVaR mean-risk objective**: maximize `(1−λ)·E[profit] − λ·CVaR_α(loss)` via the
Rockafellar-Uryasev linearization (VaR auxiliary `η`, tail slacks
`z_s ≥ loss_s − η`). Sweeping `λ` traces the mean-CVaR frontier. Defaults: tail level
`α = 0.95`, risk weight `λ = 0` for the risk-neutral problem.

### Recourse policy and estimation

Realize the recourse as a **receding-horizon (MPC) policy**: execute the committed
action for the current window, then re-solve the remaining horizon at updated realized
prices, carrying SoC as the linking state, warm-started from the previous window.

Estimate the decision-value metrics **out-of-sample**: fit the first-stage decision on
a scenario set, then evaluate on *disjoint* realized paths under the backtest's
walk-forward and leakage discipline.

## Rationale

**The structure escapes the collapse for a provable reason.** With the day-ahead price
set to the scenario mean, expected profit reduces to `E_s[Σ_t Δt π^(s)_t g^(s)_t]`, so
`g^DA` enters *only* through the budget constraint. A finite `ρ` makes the commitment
the central point each scenario deviates from, and the mean schedule is a suboptimal
centre for a spread of scenarios, so VSS > 0.

**Interpretable limits bracket the value.** Both `ρ → 0` (no recourse) and `ρ → 1`
(unlimited recourse) drive VSS → 0, and the value peaks in between. The two limits are
exact golden-oracle cases, and the VSS-versus-`ρ` curve is a natural figure.

**CVaR is scenario-native and coherent.** It is defined directly over the discrete
scenario set, needs no separate uncertainty-set construction, and its
Rockafellar-Uryasev form is linear, so the program stays a MILP with no new dependency.
It also **adds value single-shot**: the term is piecewise-linear in the outcomes, so
the expectation-collapse argument does not apply and the risk-averse solution differs
from the mean-value solution even without recourse.

**MPC is the honest name for intraday re-optimization.** A plant model, state
continuity across windows, a re-optimization trigger per period, and forecasts as the
disturbance is exactly receding-horizon control. Warm-starting is justified by latency,
not pedigree: each re-solve is a small perturbation of the last.

**Out-of-sample is the only honest VSS.** Evaluating on the fitting scenarios inflates
it, because the decision has seen the futures it is scored against. Held-out realized
paths make the reported number a generalization estimate, consistent with how the
deterministic backtest already reports value.

## Consequences

- Two structural knobs, `ρ` and the day-ahead price, and two risk knobs, `α` and `λ`;
  all have interpretable limits and defaults.
- Second-stage size is `S` copies of the deterministic model. At `S ≈ 50`, `T = 24`
  that is ~1,200 binaries, well within HiGHS.
- The wait-and-see value equals the backtest's perfect-foresight ceiling averaged over
  scenarios, so the deterministic and stochastic gates share one ceiling definition.
- The recourse simulator lives in `bess.recourse` (importing `bess.optimizer` only);
  the planner and metric harness live in `bess.stochastic`. Both fill already-declared
  layering contracts.
- The gate is a *measured* positive out-of-sample VSS, not an asserted one. A
  non-positive value indicts the construction and is surfaced, not suppressed.
- The robust counterpart is described in the formulation's out-of-scope list; adding
  it later is additive rather than a rewrite.

## Failure mode

**The budget is set so loose that recourse is effectively unlimited** and VSS ≈ 0
throughout. Signal: the value collapses across all `ρ`, not just at the limits. The
VSS-versus-`ρ` sweep is part of the gate, so a flat-zero curve is visible immediately.

**The frontier is flat**, because scenarios are near-symmetric so tail and mean move
together. Signal: no downside reduction versus `λ = 0` under a ±10% price stress, which
the gate applies.

**VSS is positive in-sample but zero or negative out-of-sample**, meaning the plan
overfit its fitting scenarios. Signal: a large in-sample versus out-of-sample gap. The
gate is the out-of-sample number; the in-sample value is a diagnostic only.

## Alternatives considered

- **A purely financial day-ahead position** with no budget coupling. The first stage
  washes out entirely and the problem degenerates to wait-and-see: a different collapse.
- **Committing only the mutual-exclusion direction**, adapting power intraday. Needs no
  new parameter, but the resulting value is tiny for smooth price shapes, since
  directions rarely flip across scenarios.
- **The full here-and-now commitment.** The trap itself, kept as a golden oracle.
- **Bertsimas-Sim Γ-budget robust optimization.** Rejected as primary because it does
  not consume the scenario probabilities and yields a single conservative point rather
  than a probability-weighted frontier. Kept as the documented alternative.
- **A hard chance constraint.** Introduces per-scenario indicator binaries and a big-M,
  turning a soft coherent objective into a harder combinatorial constraint.
- **Mean-variance.** Variance penalizes upside symmetrically; CVaR is the right tail
  object.
- **A single two-stage solve with no rolling deployment.** Enough to *define* VSS, but
  it does not demonstrate a deployable intraday policy.
- **In-sample VSS**, and **perfect-foresight recourse as the policy**. The first is
  optimistically biased; the second is the ceiling, not something executable.
