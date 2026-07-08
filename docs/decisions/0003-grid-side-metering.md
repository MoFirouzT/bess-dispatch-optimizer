# ADR-0003: Grid-side metering, efficiency in the SoC balance, never in the objective

**Status:** Accepted
**Date:** 2026-06-24 *(estimated; project foundation)*

*Back-filled (0001–0008); the date is the estimated inception date, not when this
file was written. This is the project's highest-priority correctness rule;
`CLAUDE.md` §1 and the `formulation.md` preamble state it, and this ADR records
why it is locked.*

## Context

Power variables can be metered at two points: the grid / AC terminal, or the
cell. The choice determines where round-trip efficiency `η^rt = η^ch · η^dis`
appears. Placing an efficiency factor in the revenue/objective expression is a
common and silent modelling error: it double-counts losses (or credits them),
distorts the arbitrage economics, and is invisible on a 1 MWh unit where many
numbers coincide.

## Decision

All power variables are measured at the **grid terminal**. Efficiency therefore
lives **only in the state-of-charge balance and never in the objective**:

- charging draws `p^ch_t` from the grid, but only `η^ch · p^ch_t` reaches storage;
- delivering `p^dis_t` to the grid withdraws `p^dis_t / η^dis` from storage.

Round-trip efficiency is **emergent** from this balance, not a separate term. The
canonical statement, with the SoC-balance equation and the metering figure, is in
[formulation.md § Conventions](../formulation.md); this ADR does not restate the
math. Notation is fixed by [conventions.md](../conventions.md).

## Consequences

- **Easier:** the cash flow is a clean `π_t · (p^dis_t − p^ch_t) · Δt`; losses are
  accounted exactly once, in the physics. Arbitrage and degradation economics stay
  correct across asset sizes and efficiencies.
- **Harder:** contributors must resist the intuitive "multiply revenue by
  efficiency" shortcut; the discipline is a standing review item.
- **Enforced by:** the SoC-balance **property test** (the `e_t` invariant holds for
  any valid input), the golden oracles (whose objective values assume grid-side
  cash flow), and `CLAUDE.md` §1 ("if you find an efficiency term in the objective,
  stop, the formulation is wrong").

## Failure mode

An efficiency factor creeps into the revenue term during a refactor. Signal: the
golden objective values shift, or the property test's SoC trajectory diverges from
the metered energy. Both gates fire immediately, which is the point of pinning
them.

## Alternatives considered

- **Cell-side metering (efficiency in the objective).** Rejected: it double-counts
  losses in the cash flow and detaches revenue from the metered grid energy the
  market actually settles. Grid-side is both physically correct at the settlement
  point and keeps the objective linear and loss-free.
