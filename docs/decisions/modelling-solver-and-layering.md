# The build substrate: Pyomo, HiGHS, and mechanically enforced layering

**Status:** Accepted
**Date:** 2026-06-24 *(estimated; project foundation)*

*Back-filled at project inception, then consolidated on 2026-07-28 from three
separate records (modelling layer, solver, toolchain) that were each too thin to
stand alone and are one choice in practice: what the project is built on.*

## Context

The optimizer needs an algebraic modelling layer that can express a MILP with a
binary charge flag and big-M logical constraints, a solver that runs in CI and on
any machine without licence friction, and a *mechanical* guard on the module
layering. The third is the one that erodes without enforcement: layering discipline
that lives only in a document decays the first time someone adds an import that
quietly inverts the dependency chain.

## Decision

**Pyomo** is the single modelling layer throughout `bess.optimizer`. Its
concrete-model API expresses grid-side power variables, the SoC balance, and the
big-M charge-exclusivity constraint directly, and it stays solver-agnostic.

**HiGHS** via `highspy` is the default solver, driven through Pyomo's `appsi_highs`
interface, with Gurobi available as an optional faster backend. The model is written
to the common Pyomo surface, so the swap is a solver-name change rather than a
re-formulation.

`appsi_highs` (the APPSI persistent interface) is preferred over the file-based
`SolverFactory("highs")` path for two reasons that matter here. It calls HiGHS
in-process, so each solve skips the `.nl`/`.lp` write-and-read round trip. It is
also persistent: coefficients and right-hand sides can be updated in place and
re-solved without rebuilding the model, which suits the rolling-window backtest and
the serving path, where the same model is re-solved against a fresh price vector
under a solve-time budget ([dispatch circuit breaker](dispatch-circuit-breaker.md)).

**Tooling:** `uv` for environments and dependencies with a lockfile; `ruff` for
both lint and format (`E, F, I, UP, B, SIM`), replacing flake8 + black + isort with
one tool; and **import-linter** (`uv run lint-imports`) enforcing the layering as
contracts in `pyproject.toml`.

## Consequences

- **Easier:** one modelling vocabulary from the deterministic core through the
  stochastic layer. The suite runs anywhere, token- and licence-free, so CI needs
  no commercial entitlement and any reader can reproduce it. An illegal import
  fails the build rather than passing review unnoticed.
- **Harder:** Pyomo is verbose and heavier than a NumPy-native layer, and model
  build time must be watched as horizons grow. HiGHS can be slower than Gurobi on
  the largest MILPs, which is why the serving path carries a solve-time budget.
  New modules must be placed in a layering contract before they can import across
  layers.
- **Enforced by:** `highspy` as a core dependency; CI running `ruff check`,
  `ruff format --check`, and `lint-imports`; the `[tool.importlinter]` contracts.
  Golden oracles are solver-tolerant (they assert the optimum, which is
  solver-independent), so the optional Gurobi backend cannot change a gate.

## Failure mode

Model-build overhead dominates on a long horizon, or HiGHS times out on a horizon a
contributor scales up. Signal: solve wall-clock dominated by construction, or the
serving budget tripping its breaker. Mitigation: build tuning, a shorter horizon, or
the Gurobi backend.

Separately, a new module imports "upward" and inverts the chain (for example
`optimizer` importing `api`). Signal: `lint-imports` fails in CI naming the broken
contract. Mitigation: fix the import, or amend the contract deliberately if the
architecture genuinely changed.

## Alternatives considered

- **linopy** (xarray-native, lightweight) and **CVXPY** (disciplined convex
  programming). Both rejected for the modelling layer: linopy had no mature
  two-stage or decomposition ecosystem, and CVXPY's DCP ruleset is awkward for
  big-M logical constraints.
- **A commercial solver as the default.** Rejected: breaks token-free CI and
  reproducibility for readers without a licence.
- **CBC.** Licence-free like HiGHS, but older and generally slower on this class of
  MILP.
- **pip / poetry**, and **flake8 + black + isort**. Rejected on speed and on
  config surface; `uv` and `ruff` subsume both.
- **Layering by convention and review only.** Rejected: not mechanically enforced,
  so it decays. import-linter makes the chain a build gate.

*Historical note: the original modelling-layer rationale cited `mpi-sppy` (a Pyomo
library) as the intended decomposition substrate for the stochastic layer. That path
was not taken: the two-stage program is LP-representable and solves directly on
HiGHS with no new dependency. Pyomo's decomposition ecosystem remains available and
unused.*
