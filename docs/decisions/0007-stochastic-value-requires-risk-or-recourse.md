# ADR-0007: Stochastic value requires a risk-aware objective and/or genuine recourse (avoid the VSS=0 trap)

**Status:** Accepted
**Date:** 2026-06-24 *(estimated; project foundation)*

*Back-filled (0001–0008); the date is the estimated inception date, not when this
file was written. A forward-looking design constraint on the not-yet-built
Release-2 stochastic layer (R2.2+); recorded now so R2 is designed around it
rather than discovering it late.*

## Context

A two-stage stochastic program with a **risk-neutral linear objective and full
recourse** frequently yields a **value of the stochastic solution (VSS) of
essentially zero**: the deterministic mean-scenario ("expected value") solution is
already optimal in expectation, so the stochastic machinery buys nothing
measurable. This is a well-known trap; building the stochastic layer without
guarding against it produces an elaborate model that demonstrably adds no value
over the R1 deterministic core.

## Decision

The Release-2 stochastic layer must introduce **at least one** of:

- a **risk-aware objective** (e.g. CVaR / mean-risk), so the stochastic solution
  hedges tail outcomes the expected-value solve ignores; and/or
- **genuine non-anticipative recourse** structure in which the deterministic
  mean-scenario solution is provably suboptimal.

VSS / EVPI are reported as first-class outputs of the stochastic phase so the
value is measured, not assumed. This constrains the R2.2 spec and objective
design.

## Consequences

- **Easier:** the stochastic layer is designed from the start to produce
  measurable value; the R1 deterministic solve ([ADR-0004](0004-two-release-structure.md))
  is the honest baseline VSS is computed against.
- **Harder:** rules out the simplest risk-neutral two-stage model; the objective
  and recourse structure need deliberate design.
- **Enforced by:** the R2.2 spec's acceptance gate (a VSS/EVPI report on a scenario
  set where the stochastic solution beats the mean-scenario solution). Gate to be
  written with that phase.

## Failure mode

R2.2 ships a risk-neutral full-recourse model and reports VSS≈0, making the whole
layer look worthless. Signal: VSS/EVPI ≈ 0 on the phase's own scenario set.
Mitigation: this ADR makes a non-trivial objective or recourse structure a
precondition of the phase.

## Alternatives considered

- **Risk-neutral two-stage with full recourse (the simplest model).** Rejected as
  the deliverable: the VSS=0 trap. Kept only as an internal sanity baseline that
  the risk-aware / recourse model must beat.
