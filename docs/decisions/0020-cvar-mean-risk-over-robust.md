# ADR-0020: Risk model is a CVaR mean-risk frontier, not a Bertsimas-Sim robust budget

**Status:** Accepted
**Date:** 2026-07-09
**Supersedes / Superseded by:** none (implements [ADR-0007](0007-stochastic-value-requires-risk-or-recourse.md)'s risk-aware arm)

## Context

[ADR-0007](0007-stochastic-value-requires-risk-or-recourse.md) allows a risk-aware objective as one way to escape VSS = 0; the master plan names three candidates: CVaR, a hard chance constraint, and a Bertsimas-Sim Γ-budget robust formulation. R2.3 needs one primary risk model that composes with R2.2's discrete scenario set and adds value even single-shot (risk aversion bending the objective, independent of recourse).

## Decision

Use a **CVaR mean-risk objective** as the primary risk model: maximize `(1−λ)·E[profit] − λ·CVaR_α(loss)` via the Rockafellar-Uryasev linearization (VaR auxiliary `η`, tail slacks `z_s ≥ loss_s − η`, `CVaR = η + (1/(1−α))·Σ p_s z_s`). Sweeping `λ ∈ [0,1]` traces the mean-CVaR frontier. Keep the **Bertsimas-Sim Γ-budget robust** formulation as the documented compared alternative (not built); hard chance constraints are out of scope.

## Rationale

- **Scenario-native.** CVaR is defined directly over the discrete `{(π^(s), p_s)}` set R2.2 produces; no separate uncertainty-set construction is needed, unlike the robust budget.
- **Coherent and LP-representable.** CVaR is a coherent risk measure and its Rockafellar-Uryasev form is linear, so the program stays a MILP on HiGHS with no new dependency and no nonconvexity.
- **A smooth frontier, not a single point.** The `λ` sweep yields the risk-vs-return frontier that is the Release-2 headline visual; the robust Γ knob gives a coarser conservatism dial.
- **Adds value single-shot.** The CVaR term is piecewise-linear in the outcomes, so the expectation-collapse argument does not apply: the risk-averse solution differs from the mean-value solution even without recourse, giving the phase a second, recourse-independent value source.
- **Mirrors the project's baseline pattern.** Naming one governed method and keeping the alternative as a documented comparison matches [ADR-0014](0014-cqr-over-split-conformal.md) (CQR vs split) and [ADR-0018](0018-forward-selection-over-kmeans.md) (forward vs k-means).

## Consequences

- Two scalar knobs: tail level `α` (default 0.95) and risk weight `λ` (0 = risk-neutral RP, swept for the frontier).
- The gate checks the frontier is monotone (expected profit non-increasing, downside non-worsening as `λ` grows) and that the averse solution reduces tail loss under ±10% price error.
- The robust counterpart is described in the formulation's out-of-scope list; adding it later is additive, not a rewrite.

## Failure mode

The frontier is flat (CVaR term never bends the decision), e.g. because scenarios are near-symmetric so tail and mean move together. Signal: no downside reduction versus `λ = 0` under the price stress. Mitigation: the ±10% stress gate makes a hollow risk term visible.

## Alternatives considered

- **Bertsimas-Sim Γ-budget robust optimization.** A worst-case-over-an-uncertainty-set model with a tunable conservatism budget Γ; rejected as primary because it does not consume the scenario probabilities and yields a single conservative point rather than a probability-weighted frontier. Kept as the documented alternative.
- **Hard chance constraint `P(profit > 0) ≥ β`.** Introduces per-scenario binaries for the indicator and a big-M, turning a soft, coherent objective into a harder combinatorial constraint; the soft CVaR objective achieves the same downside-control intent without it. Out of scope.
- **Mean-variance (Markowitz).** Variance penalizes upside symmetrically and is not a downside/tail measure; CVaR is the right tail-risk object for this problem.
