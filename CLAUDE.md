# CLAUDE.md — operating contract for this repo

Built phase-by-phase under strict formulation discipline. Read this file, then `docs/STATE.md`, at the start of every session.

The portable method (document tiers, the phase workflow, the writing charter, working preferences) lives in the `project-discipline` skill. This file holds what is specific to this project. Section numbers are stable: frozen specs cite `CLAUDE.md` §1, §2, §3 and §7 by number.

## 1. Math discipline (highest priority)

- The math is defined in `docs/formulation.md` — the single source of truth. NEVER change a constraint, objective term, or efficiency placement without (1) updating `formulation.md` in the same change and (2) updating/adding a golden test.
- Before editing `src/bess/optimizer/`, restate the relevant constraint from `formulation.md` and the invariant it must satisfy.
- **Power variables are grid-side; efficiency lives in the SoC balance, never in the objective.** If you ever find an efficiency term in the revenue/objective expression, stop — the formulation is wrong.
- Golden tests (`tests/golden/`) and property tests (`tests/property/`) are gates. Do NOT weaken, skip, `xfail`, or loosen tolerances to make them pass. A failing gate means the formulation or the code is wrong — surface it, don't suppress it.
- **Ground new theory in a source when it warrants one — the human decides, it is not a fixed per-part procedure.** Standard, textbook-ubiquitous techniques (e.g. big-M mutual exclusion) need no governing reference. House conventions win for shared quantities: `docs/conventions.md` and the `formulation.md` preamble fix grid-side power, per-unit SoC, `π/e/η/Δt`, and unit-suffixed names, and a reference's notation is reconciled to those. The full rule, including what a `formulation.md` summary may contain and the requirement to verify edition and section rather than cite from memory, is in the `project-discipline` skill.

## 2. Documentation architecture (four tiers)

Strategy stays private; everything committed describes the project, not how to win a job.

- **Tier 0 — `planning/` (GITIGNORED, never commit):** the master plan and the open-questions log.
- **Tier 1 — public face:** `README.md`, `docs/architecture.md`.
- **Tier 2 — canonical references:** `docs/formulation.md` and its `-uncertainty` / `-evaluation` companions (math), `docs/glossary.md`, `docs/conventions.md`, `docs/market_reference.md`, `docs/references.md`, `docs/decisions/` (ADRs).
- **Tier 3 — per-phase work orders:** `docs/specs/<subject>.md`, frozen at approval.

What each tier is for, and where a given question's answer belongs, is in the `project-discipline` skill.

**Governing rule:** strategy / positioning / career / interview content lives ONLY in Tier 0. If you are about to write "resume", "hiring", "interview", "anti-candidate", or similar into a committed file, stop and leave it out.

**Writing quality:** all committed docs follow the writing charter in `docs/conventions.md` §7. Five rules are enforced by `scripts/lint_docs.py` in CI: no em dashes, an `*Assumes:*` reader line on canonical docs, the ~600-line cap, no career/positioning words, and no coined `-able`/`-ability` words. That script also binds the checkable claims about this code (`bess.x.y` module references, `formulation*.md §R<n>.<m>` citations, the `Depends on:` graph). Read §7 before writing or editing docs.

## 3. Phase workflow (spec-first)

Spec, approval, failing tests, then implementation, as the `project-discipline` skill sets it out. Here that means: the work order is `docs/specs/<subject>.md` from `_TEMPLATE.md`, drafted with the `formulation.md` delta and approved with it **before any implementation**; the gates are `tests/golden/` and `tests/property/`; and a closed phase gets a ledger row in `docs/specs/README.md`.

One phase at a time. Do not start a Release-2 module until Release-1 gates are green.

## 4. Session continuity

- `docs/STATE.md` holds: current phase, what's done, what's next, known blockers. Read it first; update it at the end of every working session.
- Resume from `STATE.md` + the active spec; you don't need to re-read everything.

## 5. Layering

- Five import-linter contracts live in `pyproject.toml` under `[tool.importlinter]` and run in CI as `uv run lint-imports`. They fix the layer order of the dispatch chain, keep `backtest` and `studies` off the serving chain, and make `data` a leaf. Read them there and change them there: the enforced copy is the only one that cannot rot, and a restatement here already had.

## 6. Commands

- env / deps: `uv sync` · run: `uv run <cmd>`
- lint + format: `ruff check .` · `ruff format .` · types: `uv run mypy src`
- tests: `uv run pytest` · coverage: `uv run pytest --cov=bess` (CI gates this at 85%, measured with every optional group installed)
- layers: `uv run lint-imports`
- docs: `uv run python scripts/lint_docs.py` (writing charter — `conventions.md` §7)
- docs, as CI sees them: `WORD_LIST= uv run python scripts/lint_docs.py` — the coined-word check reads the system word list, which differs by OS, so this lower bound is what proves a push survives CI. Regenerate the repo's own vocabulary with `--vocabulary`, never by hand.

## 7. Guardrails (known failure modes)

- Don't invent the ENTSO-E schema from memory — fetch and print a real sample first, then code against the actual shape.
- Don't over-build: no Kubernetes, no dashboards. The spec's "out of scope" section is binding.
- After any optimizer refactor, re-run the golden tests — they catch silent changes to constraint meaning.

## 8. Overrides

Rules from the `project-discipline` skill this project deliberately does not follow, each with the reason. This section is the only supported way to turn one off: a rule that is silently ignored looks identical to a rule that was forgotten.

- None.
