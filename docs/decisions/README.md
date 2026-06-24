# Architecture Decision Records

This directory captures decisions that are expensive to reverse. Each ADR is one Markdown file with a numeric prefix. An ADR is the stable answer to "why is it like this?" — cheaper to write once than to keep re-deriving (and it stops an agent, or a future you, from quietly reverting a decision while "improving" the code).

## How to propose a new ADR

1. Pick the next free number; create `XXXX-short-slug.md` from the template below.
2. Open a draft PR titled `adr/XXXX-short-slug`; discuss.
3. Once accepted, set `Status: Accepted` and merge.
4. **Never edit an Accepted ADR.** If the decision changes, write a *new* ADR that supersedes it and update both `Status` lines.

## Statuses

`Proposed` (under discussion) · `Accepted` (in force) · `Superseded by ADR-XXXX` · `Rejected` (kept for the record).

## Template

```markdown
# ADR-XXXX: <short title>

**Status:** Proposed | Accepted | Superseded by ADR-YYYY | Rejected
**Date:** YYYY-MM-DD
**Supersedes / Superseded by:** (optional links)

## Context
The problem, the constraints, what was considered.

## Decision
The chosen approach, stated as concisely as possible.

## Consequences
What gets easier, what gets harder, what new questions arise, and which
check (CI, lint, import-linter, a golden test) enforces this mechanically.

## Failure mode
How this decision could go wrong in practice, and the signal that would reveal it.

## Alternatives considered
The other options and why they were rejected.
```

## Index (starter — these are the foundational decisions to formalize; status `Proposed` until written)

| # | Title | Status |
| --- | ------- | -------- |
| 0001 | Pyomo for modelling (not linopy or CVXPY) — chosen for the `mpi-sppy` two-stage / Benders path | Proposed |
| 0002 | HiGHS as the default solver; Gurobi (academic licence) as an optional faster backend | Proposed |
| 0003 | Grid-side metering: efficiency in the SoC balance, never in the objective | Proposed |
| 0004 | Two-release structure; deterministic core ships before the stochastic layer | Proposed |
| 0005 | Commit real fixture data so the test suite runs without an API token | Proposed |
| 0006 | Day-ahead is 15-minute native; the R1.1 hourly core is a deliberate simplification | Proposed |
| 0007 | Stochastic value requires a risk-aware objective and/or genuine recourse (avoid the VSS=0 trap) | Proposed |
| 0008 | `uv` + `ruff` toolchain; import-linter enforces the dependency layering | Proposed |

Write each as its own file when the decision is locked. Keep this index in sync.
