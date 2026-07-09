# ADR-0019: The two-stage construction is day-ahead commitment + budget-limited intraday recourse

**Status:** Accepted
**Date:** 2026-07-09
**Supersedes / Superseded by:** none (implements [ADR-0007](0007-stochastic-value-requires-risk-or-recourse.md) concretely)

## Context

[ADR-0007](0007-stochastic-value-requires-risk-or-recourse.md) commits R2 to a stochastic layer that provably escapes the VSS = 0 trap. R2.3 must now fix the *specific* two-stage structure. The trap is exact: with the whole 24-hour dispatch as a single here-and-now decision, a risk-neutral linear objective makes the stochastic solution equal to the mean-value solution (`E_s[π^(s)·x] = π̄·x`), so VSS = 0. A construction has to break the collapse while (a) reusing the R1.1 physics per scenario, (b) staying self-contained and token-free-testable, and (c) yielding a hand-computable VSS for a golden oracle.

## Decision

Model **first-stage** as a non-anticipative day-ahead net-export schedule `g^DA` (itself R1.1-feasible), and **second-stage** as per-scenario dispatch `g^(s)` (full R1.1 physics at the realized price `π^(s)`) tied to the commitment by a **recourse budget** `|g^(s)_t − g^DA_t| ≤ ΔP̄ = ρ·P̄`, `ρ ∈ [0,1]`. Day-ahead volume settles at the known day-ahead price `π^DA` (default the scenario mean `π̄`), the intraday deviation at the realized `π^(s)`. The intraday/realized signal is derived from the R2.2 scenario set, so no new data feed is introduced.

## Rationale

- **It escapes the collapse for a provable reason.** With `π^DA = π̄`, the expected profit reduces to `E_s[Σ_t Δt π^(s)_t g^(s)_t]`, so `g^DA` enters *only* through the budget constraint. A finite `ρ` makes `g^DA` the central point each scenario deviates from within `ΔP̄`; the mean schedule is a suboptimal center for a spread of scenarios, so `RP > EEV` and VSS > 0.
- **Interpretable limits bracket the value.** `ρ → 0` (no recourse) and `ρ → 1` (unlimited recourse) both drive VSS → 0; VSS peaks at intermediate `ρ`. The two limits are exact golden-oracle cases (VSS = 0), and a VSS-vs-`ρ` curve is a natural figure.
- **Reuses R1.1 unchanged.** Each scenario's second stage is the existing deterministic model; only the shared commitment, the budget-coupling, and the settlement accounting are new. `WS = Σ_s p_s V*(π^(s))` is exactly R1.4's perfect-foresight ceiling averaged over scenarios, tying the metric back to the deterministic gate.
- **Self-contained.** The intraday signal comes from R2.2's scenarios; no intraday market feed is needed for the gate.

## Consequences

- One new parameter `ρ` (recourse fraction) and one new price `π^DA` (default `π̄`); both have interpretable limits and defaults.
- Second-stage size is `S` copies of the R1.1 model (`S·T` binaries `u^(s)_t`); at `S ~ 50`, `T ~ 24` this is ~1200 binaries, well within HiGHS.
- VSS is reported out-of-sample ([ADR-0021](0021-mpc-recourse-out-of-sample-vss.md)); the gate is a *measured* positive VSS, not an asserted one.

## Failure mode

`ρ` is set so loose (or `π^DA` chosen) that recourse is effectively unlimited and VSS ≈ 0 on the phase's own instance. Signal: VSS collapses across all `ρ`, not just at the limits. Mitigation: the VSS-vs-`ρ` sweep is part of the gate, so a flat-zero curve is visible immediately and indicts the construction rather than hiding behind a single number.

## Alternatives considered

- **Purely financial day-ahead position (no budget coupling).** With `π^DA = π̄` the first stage washes out entirely and the problem degenerates to `WS`; rejected (a different collapse).
- **Commit only the mutual-exclusion direction `u_t`, adapt power intraday.** Reuses the model with no new parameter, but the VSS from direction-only commitment is tiny for smooth price shapes (directions rarely flip across scenarios), too weak to gate on robustly.
- **Full 24-hour here-and-now commitment (the naive model).** The VSS = 0 trap itself; kept only as golden oracle 1.
- **An explicit intraday order-book / imbalance market.** Honest but needs market-microstructure modeling and a second data feed; deferred to R3 (out of scope here).
