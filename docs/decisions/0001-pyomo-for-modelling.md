# ADR-0001: Pyomo as the modelling layer (not linopy or CVXPY)

**Status:** Accepted
**Date:** 2026-06-24 *(estimated; project foundation)*

*Back-filled: a project-inception decision, written up here as part of
formalizing the foundational ADRs (0001–0008). The date is the estimated decision
date (project foundation), not when this file was written.*

## Context

The optimizer needs an algebraic modelling layer to express a MILP with a
binary charge flag and logical (big-M) constraints, and to swap solver backends.
The choice also has to survive the Release-2 roadmap: a two-stage stochastic /
Benders / progressive-hedging path (R2.2–R2.4) built on `mpi-sppy`, which itself
is a Pyomo library. Picking a modelling layer with no decomposition ecosystem
would mean re-tooling at exactly the phase where the hard math starts.

## Decision

Use **Pyomo** as the single modelling layer throughout `bess.optimizer`. Its
concrete-model API expresses the grid-side power variables, the SoC balance, and
the big-M charge-exclusivity constraint directly, and it is the substrate
`mpi-sppy` extends for the stochastic layer.

## Consequences

- **Easier:** one modelling vocabulary from R1.1 through the R2 stochastic layer;
  no rewrite when decomposition arrives. Solver-agnostic (see
  [ADR-0002](0002-highs-default-solver.md)).
- **Harder:** Pyomo is verbose and heavier than a NumPy-native layer; model build
  time is non-trivial and must be watched as horizons grow.
- **Enforced by:** Pyomo is the modelling API in `bess.optimizer`; the golden
  tests pin the resulting objective/schedule regardless of internals.

## Failure mode

Model-build overhead dominates on large horizons, or the `mpi-sppy` integration
proves awkward. Signal: solve wall-clock dominated by construction, or the R2.2
spec hitting friction at the two-stage boundary. Mitigation is local (build
tuning); the decomposition ecosystem is the reason not to switch away.

## Alternatives considered

- **linopy.** xarray-native, lightweight, pleasant for pure LP/MILP. Rejected:
  no mature two-stage / Benders / progressive-hedging ecosystem, which is the
  Release-2 requirement.
- **CVXPY.** Excellent for disciplined convex programming. Rejected: geared to
  convex problems, the DCP ruleset is awkward for big-M logical constraints, and
  it is not built for the custom decomposition schemes R2.4 targets.
