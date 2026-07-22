# CLAUDE.md — operating contract for this repo

Built phase-by-phase under strict formulation discipline. Read this file, then `docs/STATE.md`, at the start of every session.

## 1. Math discipline (highest priority)

- The math is defined in `docs/formulation.md` — the single source of truth. NEVER change a constraint, objective term, or efficiency placement without (1) updating `formulation.md` in the same change and (2) updating/adding a golden test.
- Before editing `src/bess/optimizer/`, restate the relevant constraint from `formulation.md` and the invariant it must satisfy.
- **Power variables are grid-side; efficiency lives in the SoC balance, never in the objective.** If you ever find an efficiency term in the revenue/objective expression, stop — the formulation is wrong.
- Golden tests (`tests/golden/`) and property tests (`tests/property/`) are gates. Do NOT weaken, skip, `xfail`, or loosen tolerances to make them pass. A failing gate means the formulation or the code is wrong — surface it, don't suppress it.
- **Ground new theory in a source when it warrants one — the human decides, it is not a fixed per-part procedure.** When a part introduces genuinely new theory, sourcing it to a published reference (and recording that in `docs/references.md`) is at the human's discretion, decided case by case, not a mandatory step for every part. Standard, textbook-ubiquitous techniques (e.g. big-M mutual exclusion) need no governing reference. Whenever a source *is* used: **house conventions win for shared quantities** (`docs/conventions.md` + the `formulation.md` preamble: grid-side power, per-unit SoC, `π/e/η/Δt`, unit-suffixed names) — reconcile the reference's notation to house style and note any mapping; keep the `formulation.md` summary *brief and self-contained* (only what the project implements, plus any gate-critical nuance, plus an explicit "considered but out of scope" list); and **verify claims before relying** — cite edition + chapter/section, never from memory.

## 2. Documentation architecture (four tiers)

Strategy stays private; everything committed describes the project, not how to win a job.

- **Tier 0 — `planning/` (GITIGNORED, never commit):** the master plan and the open-questions log. Source of truth for *why* and *what to build*. Read it for context; never copy its career / positioning / interview framing into a committed file.
- **Tier 1 — public face (committed):** `README.md`, `docs/architecture.md`. Stable, minimal, project-only.
- **Tier 2 — canonical references (committed):** `docs/formulation.md` (math), `docs/glossary.md`, `docs/references.md` (source references, for parts that use one), `docs/decisions/` (ADRs).
- **Tier 3 — per-phase work orders (committed):** `docs/specs/<phase>.md`. One per phase, generated from the master plan + this contract, reviewed by the human, frozen, then implemented.

**Governing rule:** strategy / positioning / career / interview content lives ONLY in Tier 0. If you are about to write "resume", "hiring", "interview", "anti-candidate", or similar into a committed file, stop and leave it out.

**Writing quality:** all committed docs follow the writing charter in `docs/conventions.md` §7 (structure, audience, prose mechanics, governance). Four rules are enforced by `scripts/lint_docs.py` in CI — no stacked em dashes, an `*Assumes:*` reader line on canonical docs, the ~600-line cap, and no career/interview words. Read §7 before writing or editing docs.

## 3. Phase workflow (spec-first)

1. Human picks the phase. You draft or refresh `docs/specs/<phase>.md` from `docs/specs/_TEMPLATE.md` + the master plan, plus the `formulation.md` delta.
2. Human reviews and approves the spec + formulation **before any implementation**.
3. You write the phase's golden + property tests **first** (failing).
4. You implement to green. Do not proceed to the next phase until the gate passes.
5. One phase at a time. Do not start a Release-2 module until Release-1 gates are green.

## 4. Session continuity

- `docs/STATE.md` holds: current phase, what's done, what's next, known blockers. Read it first; update it at the end of every working session.
- Resume from `STATE.md` + the active spec; you don't need to re-read everything.

## 5. Layering

- import-linter contract enforced in CI: `api → explain → stochastic → recourse → optimizer → validation → assets`; `forecaster` / `scenarios` feed `stochastic`; `optimizer` must NOT import `api`.

## 6. Commands

- env / deps: `uv sync` · run: `uv run <cmd>`
- lint + format: `ruff check .` · `ruff format .` · types: `uv run mypy src`
- tests: `uv run pytest` · coverage: `uv run pytest --cov=bess`
- layers: `uv run lint-imports`
- docs: `uv run python scripts/lint_docs.py` (writing charter — `conventions.md` §7)

## 7. Guardrails (known failure modes)

- Don't invent the ENTSO-E schema from memory — fetch and print a real sample first, then code against the actual shape.
- Don't over-build: no Kubernetes, no dashboards. The spec's "out of scope" section is binding.
- After any optimizer refactor, re-run the golden tests — they catch silent changes to constraint meaning.
