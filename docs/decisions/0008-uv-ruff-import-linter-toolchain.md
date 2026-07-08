# ADR-0008: `uv` + `ruff` toolchain; import-linter enforces the dependency layering

**Status:** Accepted
**Date:** 2026-06-24 *(estimated; project foundation)*

*Back-filled (0001–0008); the date is the estimated inception date, not when this
file was written.*

## Context

The project needs reproducible environments, fast lint/format, and a *mechanical*
guard on the module layering (`CLAUDE.md` §5). Layering discipline that lives only
in a doc erodes: an agent or a future contributor adds an import that quietly
inverts the dependency chain, and nothing catches it.

## Decision

- **`uv`** for environment and dependency management (`uv sync`, `uv run`), with a
  lockfile for reproducibility.
- **`ruff`** for both lint and format (rule set `E, F, I, UP, B, SIM`), replacing
  the flake8 + black + isort trio with one fast tool.
- **`import-linter`** (`uv run lint-imports`) enforces the layering as contracts in
  `pyproject.toml`: the core chain `api → explain → stochastic → recourse →
  optimizer → validation → assets`, the `stochastic ← scenarios ← forecaster`
  feed, `backtest` as an offline tool barred from the serving chain, and `data` as
  a leaf.

## Consequences

- **Easier:** one fast toolchain; the layering is checked in CI, so an illegal
  import fails the build instead of passing review unnoticed.
- **Harder:** new modules must be placed in the contract before they can import
  across layers; the contracts need updating as the architecture grows.
- **Enforced by:** CI running `ruff check`, `ruff format --check`, and
  `lint-imports`; the `[tool.importlinter]` contracts in `pyproject.toml`.

## Failure mode

A new module imports "upward" and inverts the chain (e.g. `optimizer` imports
`api`). Signal: `lint-imports` fails in CI naming the broken contract. Mitigation:
the contract is the guard; fix the import or, if the architecture genuinely
changed, amend the contract deliberately (and record it).

## Alternatives considered

- **pip / poetry.** Rejected: slower resolves; `uv`'s speed and lockfile are the
  draw.
- **flake8 + black + isort.** Rejected: `ruff` subsumes all three (lint, format,
  import-sort) far faster, one config.
- **Layering by convention / review only.** Rejected: not mechanically enforced, so
  it decays; import-linter makes the chain a build gate.
