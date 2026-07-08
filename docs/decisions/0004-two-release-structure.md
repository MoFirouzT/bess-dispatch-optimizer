# ADR-0004: Two-release structure; the deterministic core ships before the stochastic layer

**Status:** Accepted
**Date:** 2026-06-24 *(estimated; project foundation)*

*Back-filled (0001–0008); the date is the estimated inception date, not when this
file was written.*

## Context

The interesting math is the stochastic / recourse layer, so the temptation is to
build it first. But the value of stochastic optimization is *measured against* a
correct deterministic baseline (VSS, EVPI, the value of the stochastic solution
are all differences from the deterministic mean-scenario solve). Without a
trustworthy deterministic core there is nothing to measure against, and no way to
tell a real stochastic gain from a modelling artefact.

## Decision

Ship in **two releases**. Release 1 is the deterministic MILP core and everything
needed to trust it: dispatch (R1.1), degradation (R1.2), pre-flight validation
(R1.3), walk-forward backtest (R1.4), and serving (R1.5). Release 2 is the
stochastic / scenarios / recourse / explainability layer (R2.x). R1 gates must be
green before any R2 module starts.

## Consequences

- **Easier:** R2 builds on a pinned, tested baseline; stochastic value is a clean
  delta against R1's deterministic solve. Each release is independently shippable.
- **Harder:** the headline stochastic work waits behind the deterministic
  plumbing; discipline is needed not to jump ahead.
- **Enforced by:** the `CLAUDE.md` §3 phase workflow ("one phase at a time; do not
  start a Release-2 module until Release-1 gates are green") and the spec ordering
  in `docs/specs/`.

## Failure mode

An R2 module is started against an unfinished R1 gate, and a stochastic "gain"
turns out to be a deterministic bug. Signal: R1 golden/property gates not green
while R2 work is in flight. Mitigation: the phase-gate rule above.

## Alternatives considered

- **Stochastic-first.** Rejected: no deterministic baseline to measure stochastic
  value against, higher risk, and the classic VSS≈0 trap
  ([ADR-0007](0007-stochastic-value-requires-risk-or-recourse.md)) becomes
  undiagnosable without the deterministic reference solve.
