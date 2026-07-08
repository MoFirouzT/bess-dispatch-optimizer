# ADR-0002: HiGHS as the default solver, Gurobi optional

**Status:** Accepted
**Date:** 2026-06-24 *(estimated; project foundation)*

*Back-filled (0001–0008); the date is the estimated inception date, not when this
file was written.*

## Context

The MILP needs a solver that runs in CI and on any contributor's machine with no
licence friction, while leaving room for a faster commercial backend on larger
horizons. The modelling layer ([ADR-0001](0001-pyomo-for-modelling.md)) is
solver-agnostic, so this is a swappable backend choice, not a lock-in.

## Decision

Default to **HiGHS** via `highspy`, driven through Pyomo's `appsi_highs`
interface. Keep **Gurobi** (academic licence) as an optional faster backend for
large or time-limited solves; the model is written to the common Pyomo surface
so the swap is a solver-name change, not a re-formulation.

## Consequences

- **Easier:** the suite runs anywhere, token- and licence-free; CI needs no
  commercial entitlement. Reproducible for any reader.
- **Harder:** HiGHS can be slower than Gurobi on the largest MILPs; the serving
  path therefore carries a solve-time budget and a circuit breaker
  ([ADR-0011](0011-circuit-breaker-semantics.md)).
- **Enforced by:** `highspy` is a core dependency in `pyproject.toml`; CI solves
  on HiGHS. Golden oracles are solver-tolerant (they assert the optimum, which is
  solver-independent), so the optional Gurobi backend cannot change a gate.

## Failure mode

HiGHS times out on a horizon a contributor scales up. Signal: the serving budget
trips its breaker, or a backtest solve runs long. Mitigation: shrink the horizon,
or opt into the Gurobi backend.

## Alternatives considered

- **A commercial solver as the default.** Rejected: breaks token-free CI and
  reproducibility for readers without a licence.
- **CBC.** Open-source and licence-free like HiGHS, but older and generally
  slower on this class of MILP. Rejected in favour of HiGHS's stronger
  performance and active development.
