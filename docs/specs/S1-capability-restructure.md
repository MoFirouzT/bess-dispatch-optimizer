# Spec S1. Capability restructure (vocabulary, studies split, doc recut)

**Status:** Approved (frozen 2026-07-28; six open questions resolved at review, all as proposed)
**Release:** cross-cutting (no release)  **Depends on:** every implemented phase; nothing depends on this

Reorganize how the project presents itself, without changing what it computes.
Twenty delivery phase IDs are collapsed into eight capabilities, the value studies move out of the serving chain into their own package and doc shelf, and the three documents that grew along the delivery axis (formulation, STATE, README) are recut along the subject axis.

## Why this is not an `R` phase

Every `R<n>.<m>` spec delivers a capability and carries a formulation delta, a golden oracle, or both.
This one delivers neither: it is a rename, a move, and a recut.
Giving it a capability number would put the restructure inside the very numbering scheme it exists to retire.
The `S` prefix marks a structural phase, and `scripts/lint_docs.py` skips non-`R` filenames in its `Depends on:` graph exactly as it skips `_TEMPLATE.md`, which is correct here: a structural phase depends on all phases, not on a particular one.

## Objective

Make the public structure of the project match its architecture (nine packages, eight capabilities) rather than its build order (twenty dated phases), and make "studies are not the product" a CI-enforced fact rather than a doc claim.

## Motivation

The phase IDs are an accurate build record that was quietly promoted into permanent public vocabulary.
They now appear in README status bullets, `docs/architecture.md`, formulation section headings, ADR titles, figure captions, module docstrings, and test filenames, so a reader must learn that R2.1c and R2.2c are unrelated before parsing a sentence about the tail.
The suffix series (`b`, `c`, `d`, `e`) makes this worse: those suffixes record *when a defect was found*, which is a fact about the project's history, not about its design.

Three consequences follow, and all three are already visible:

1. **`README.md` carries a twenty-item status list**, in which a measured null occupies the same visual weight as the MILP core.
2. **`docs/STATE.md` became append-only** and overflowed the 600-line cap, which was relieved by splitting off `STATE-archive.md`. That split moves the problem without changing its form: the archive is still a journal, so it will overflow again.
3. **`src/bess/stochastic/study.py` is the largest module in the repository** and it is evaluation code living inside the serving chain. `bess.backtest` is quarantined by a `forbidden` import contract; the value studies are not.

## The governing invariant

**This phase changes no number.**
No constraint, objective term, variable, default, tolerance, or measured result moves.
Every golden oracle keeps its expected value, every property test keeps its invariant, and the full suite's pass count is unchanged except where a test file is renamed.
Prose that is moved between files moves verbatim; only headings, anchors, and cross-links are rewritten.

That invariant is what makes the phase safe to review: any diff line that changes a number is a defect in this phase, not a finding.

## Formulation reference

No new math and no changed math.
`docs/formulation.md` is recut into three files by subject, with every section body moved verbatim.
Per `CLAUDE.md` §1 the formulation is the single source of truth for the model, so the file keeping that name keeps the model: `formulation.md` remains the core, and only the two derived files are new.

---

## Work item 1: capability vocabulary

Eight capability names replace twenty phase IDs in reader-facing prose.
The mapping is one-to-one onto the packages that already exist, which is the honest architecture:

| Capability | Absorbs | Packages |
| --- | --- | --- |
| Dispatch core | R1.1, R1.2, R1.3 | `bess.assets`, `bess.validation`, `bess.optimizer` |
| Data feed | R1.4b, R1.4c | `bess.data` |
| Backtest | R1.4a | `bess.backtest` |
| Serving | R1.5 | `bess.api` |
| Price forecaster | R2.1, R2.1b, R2.1c, R2.1d, R2.1e | `bess.forecaster` |
| Scenario generation | R2.2, R2.2b, R2.2c | `bess.scenarios` |
| Stochastic dispatch | R2.3 | `bess.stochastic`, `bess.recourse` |
| Dispatch explainability | R2.4 | `bess.explain` |

R1.2 folding into the dispatch core is the clearest case and sets the rule for the others: its entire delta is one objective term plus a throughput linearization, and `docs/formulation.md` already labels R1.3 "derived; no new model".
A phase that adds a term to an existing objective is a property of a capability, not a capability.

**Where the phase IDs survive, unchanged:** git history, `docs/specs/` filenames, ADR bodies, the phase ledger (work item 3), and the `Depends on:` graph between specs.
They are an accurate record of the build and stay readable as one.
They stop being the vocabulary a first-time reader has to learn.

**Anti-pattern this forbids:** introducing a new phase ID into README prose, `architecture.md`, or a figure caption. Those documents name capabilities; specs and the ledger name phases.

---

## Work item 2: the studies split

### What counts as a study

A **capability** ships behaviour the dispatch pipeline uses.
A **study** answers a question about the pipeline and ships a finding.
The seam is whether removing it changes what `POST /dispatch` returns.

By that test the studies are: the value of the stochastic solution, forecast value, tail dispatch value, bid-curve value, the storage-duration sweep, and solve-time scaling.
Four of these returned nulls, which is the project's most credible content and the reason the split matters: a null deserves a page that states it plainly, not a bullet competing with the MILP core for attention.

### The code move

`src/bess/stochastic/study.py` moves to a new `src/bess/studies/` package, a sibling of `bess.backtest`, outside the serving chain.

The seam inside `bess.stochastic` is precise and worth stating, because it is not "everything that measures something":

- **Stays** in `bess.stochastic`: `risk.py`, `twostage.py`, and `vss.py`. The Birge-Louveaux decision-value metrics in `vss.py` are defined in the formulation and computed from a single scenario set, so they are part of the program's contract.
- **Moves** to `src/bess/studies/`: the contents of `study.py`, which are multi-window empirical harnesses that fit, score, and aggregate over real days. Nothing in the program needs them.

Suggested layout, one module per study rather than one 641-line module:

```text
src/bess/studies/
    __init__.py        # re-exports the public study API
    windows.py         # window_sets, _complete_day_matrix (shared harness)
    vss_study.py       # vss_across_windows, WindowVSS
    forecast_value.py  # forecast_value*, fv_*, ForecastValue, WindowFV
    tail_value.py      # tail_value_*, TailValue, WindowTV
    bid_curve_value.py # bid_curve_value_*, BidCurveValue, WindowBCV
```

`bess.stochastic.__init__` drops the fourteen study re-exports and keeps the eight names that belong to the program.
That is a public API change for anyone importing study symbols from `bess.stochastic`; the project has no external consumers, so it is a rename, not a deprecation.

### The import contract

A new `forbidden` contract in `pyproject.toml`, taking the count from four to five:

```toml
[[tool.importlinter.contracts]]
name = "studies are offline (the serving chain must not import them)"
type = "forbidden"
source_modules = [
    "bess.api",
    "bess.explain",
    "bess.stochastic",
    "bess.recourse",
    "bess.optimizer",
    "bess.validation",
    "bess.assets",
    "bess.scenarios",
    "bess.forecaster",
]
forbidden_modules = ["bess.studies"]
```

**Note the direction, which is opposite to the backtest contract.**
`bess.backtest` sits above the optimizer and is forbidden from importing the serving chain.
The new `src/bess/studies/` legitimately imports `bess.stochastic`, `bess.scenarios`, and `bess.forecaster`, so its contract forbids the reverse edge: nothing in the chain may reach up into a study.
That single edge is the mechanical form of "studies are not the product", and it is what makes the claim survive a future refactor.

### Test and example moves

Test files move with the code and keep their contents byte-identical apart from the import line:

| From | To |
| --- | --- |
| `tests/golden/test_golden_value_study.py` | `tests/golden/test_golden_study_vss.py` |
| `tests/golden/test_golden_tail_value.py` | `tests/golden/test_golden_study_tail_value.py` |
| `tests/golden/test_golden_bid_curve_value.py` | `tests/golden/test_golden_study_bid_curve.py` |
| `tests/property/test_value_study.py` | `tests/property/test_study_vss.py` |
| `tests/property/test_tail_value.py` | `tests/property/test_study_tail_value.py` |
| `tests/property/test_bid_curve_value.py` | `tests/property/test_study_bid_curve.py` |
| `tests/integration/test_value_study_live.py` | `tests/integration/test_study_vss_live.py` |
| `tests/integration/test_tail_value_live.py` | `tests/integration/test_study_tail_value_live.py` |
| `tests/integration/test_bid_curve_value_live.py` | `tests/integration/test_study_bid_curve_live.py` |

`examples/` gets the same cut, into demonstrations and studies:

- **Studies:** `vss_study.py`, `duration_sweep.py`, `benchmark_scaling.py`.
- **Demos:** the remaining nine, which render a mechanism rather than measure a result.

The file paths stay where they are (resolved decision 3): `examples/README.md` splits into a **Studies** heading and a **Demonstrations** heading, so the reproduction commands the README quotes keep working.

### The doc shelf

```text
docs/studies/
    README.md            # index; the findings table, nulls included
    stochastic-value.md  # VSS as a per-window distribution (positive)
    forecast-value.md    # conformal vs seasonal-naive scenarios (null)
    tail-value.md        # extreme-value tail in realized euros (null)
    bid-curves.md        # price-contingent commitment (null) + the delivery gap
    target-normalization.md  # de-levelled target; null at 365d, a gain at 730d
    storage-duration.md  # the energy-to-power axis (ADR-0022)
    solve-scaling.md     # solve time vs horizon and scenario count
```

Each page: the question, the method in a short paragraph, the answer in the first three lines, the figure, the reproduction command, and a link to its spec for the design detail.
One page per study, well under the line cap.

`README.md` then carries **one** subsection, roughly six lines, that states the findings and links out.
The nulls are not buried; they are stated once, confidently, in the place a reader can absorb them, instead of spread across three long paragraphs and two figures on the front page.

---

## Work item 3: the doc recut

### The formulation, by subject

`docs/formulation.md` keeps its name and becomes the core, because `CLAUDE.md` §1 names that file as the single source of truth and the model belongs with that name.
Only the derived files change:

| File | Sections | Rough size |
| --- | --- | --- |
| `docs/formulation.md` | preamble, conventions, model at a glance, R1.1, R1.2, R1.3, R2.4 duals, changelog | ~400 lines |
| `docs/formulation-uncertainty.md` | R2.1 forecast, R2.2 scenarios, R2.3 two-stage and CVaR, R2.6 bid curve | ~150 lines |
| `docs/formulation-evaluation.md` | R1.4 backtest semantics, R2.5 value metrics, R2.6 curve scoring | ~150 lines |

The current split is by release, which cuts through the subject: R2.4's water value is the dual of R1.1's SoC balance and reads next to it, while R1.4's revenue ordering is measurement protocol that reads next to R2.5's.
The old release-split file is deleted, and its `CANONICAL` entry in `scripts/lint_docs.py` is replaced by the two new files.

### STATE: a ledger, not a journal

`docs/STATE.md` shrinks to under 100 lines and holds exactly what `CLAUDE.md` §4 promises: current phase, an eight-row capability status table, next, and known blockers.

The history is kept, in changed form.
`docs/STATE-archive.md` is compressed into a **phase ledger** in a new `docs/specs/README.md`, one row per phase:

| Phase | Date | Capability | What changed | Finding |
| --- | --- | --- | --- | --- |
| R2.5b | 2026-07-24 | Stochastic dispatch | tail dispatch value measured over real windows | null; recourse already captures a realized spike |

The ledger is the answer to "keep a brief history", and it is a better answer than a shorter journal for two reasons.
**It is bounded**: one row per phase, so roughly twenty-two rows today and one more per phase forever, where a journal grows without limit and has already overflowed the cap once.
**It keeps the part worth keeping**: the finding. What the current archive holds beyond that is session mechanics (test counts, "ruff/format/mypy clean", "this session"), which git records more accurately than prose does.

It also lives in a **stable** file rather than a volatile one.
Putting an append-only record inside the document that gets rewritten every session is what produced the 600-line `STATE.md` in the first place; separate lifecycles need separate files.
And `docs/specs/README.md` is a file the project is missing anyway: the ledger doubles as the spec index and as the phase-to-capability map that work item 1 needs for traceability.

The honest cost: compressing 417 lines of narrative to about 22 rows drops design detail.
The mitigation is that each row links its spec, and every spec carries that phase's resolved decision trail in its own Open questions section, which is where that detail belonged from the start.

### README

Target roughly 150 lines, reached mostly by the two changes above rather than by cutting prose:

1. Headline result and the problem statement (unchanged).
2. The model: objective, SoC balance, the grid-side metering rule (unchanged).
3. The architecture diagram, relabelled to capabilities.
4. **Eight capability bullets** in place of twenty phase bullets.
5. Three or four figures, the ones that show a mechanism.
6. One findings subsection linking `docs/studies/`.
7. Development, serving, data, limitations (unchanged).

---

## Build tasks

Three independently reviewable commits, in this order. Each leaves the tree green.

**Commit 1: the code move (behaviour-preserving).**

- [ ] Create `src/bess/studies/` with the module split above; move the bodies verbatim.
- [ ] Update `bess.stochastic.__init__` to drop the study re-exports; add the `studies` package docstring.
- [ ] Add the `forbidden` contract to `pyproject.toml`; confirm five contracts KEPT.
- [ ] Rename the nine test files and fix their imports; contents otherwise unchanged.
- [ ] Update `examples/vss_study.py` and `tests/unit/test_examples_smoke.py`.
- [ ] Full suite green with an unchanged pass count; `mypy`, `ruff`, `ruff format` clean.

**Commit 2: the studies shelf.**

- [ ] Write `docs/studies/` (index plus seven pages), each sourced from its spec and the archive entry.
- [ ] Replace the README's uncertainty-narrative paragraphs with the findings subsection.
- [ ] Move the study figures' prose to their pages; the figures stay in `docs/figures/`.
- [ ] Split `examples/README.md` under Studies and Demonstrations headings; leave every file path unchanged.

**Commit 3: the vocabulary and the recut.**

- [ ] Split the formulation into the three files; move section bodies verbatim; update the changelog with a "no math changed" entry.
- [ ] Update `CANONICAL` in `scripts/lint_docs.py`.
- [ ] Write `docs/specs/README.md`: spec index, phase-to-capability map, and the ledger compressed from `STATE-archive.md`.
- [ ] Delete `docs/STATE-archive.md`; cut `docs/STATE.md` to under 100 lines.
- [ ] Relabel README, `architecture.md`, and figure captions to capability names.
- [ ] Fix every cross-link and anchor; `uv run python scripts/lint_docs.py` clean.

## Acceptance gate

*Blocks:* the next capability phase (R3.1). Every box must pass.

- [ ] **No number moved.** `git diff` over `src/` and `tests/` contains no changed numeric literal, tolerance, or expected value. This is the phase's defining check and is verified by reading the diff, not by a test.
- [ ] Full suite green, pass count equal to the pre-migration count.
- [ ] `uv run lint-imports` reports **five** contracts KEPT, including the new studies contract.
- [ ] A deliberate violation of the studies contract (a temporary `import bess.studies` inside `bess.stochastic`) is caught by `lint-imports`, then reverted. A contract nobody has seen fail is not known to work.
- [ ] `uv run mypy src` clean at the current error-free state; `ruff check` and `ruff format --check` clean.
- [ ] `uv run python scripts/lint_docs.py` clean, including the anchor check across the recut formulation.
- [ ] `docs/STATE.md` under 100 lines; no doc over the 600-line cap.
- [ ] README contains no `R<n>.<m>` phase ID outside the studies findings subsection and the docs table.
- [ ] Every phase with a spec has a ledger row in `docs/specs/README.md`.
- [ ] The four null findings are each stated on their own studies page, in the page's first three lines.

## Out of scope

- **Any change to the model, defaults, or measured results.** Governed by the invariant above.
- **Renaming `src/` packages other than the study extraction.** The layer names are good and the contracts that enforce them are the strongest structural asset in the repository.
- **Renumbering or rewriting ADRs.** Chronological numbering is correct for ADRs, and `CLAUDE.md` forbids editing an accepted one.
- **Renaming spec files.** The `R` IDs stay on disk; only their use in reader-facing prose changes.
- **Deleting any study or null.** They are re-homed, never dropped.
- **README rewriting beyond the outline above.** Prose quality is a separate pass.

## Open questions

All six resolved at review, each as proposed. The proposals are kept so the section reads as the decision trail.

1. Package name: `studies` or `evaluation`? *Proposed:* `studies`. The alternative collides with `bess.forecaster.evaluate`, which does something different (per-forecast metrics, not multi-window harnesses), and the collision would need explaining every time. **Resolved:** `studies` (2026-07-28).
2. Does `vss.py` move too? *Proposed:* no. The Birge-Louveaux metrics are formulation-defined and computed from one scenario set, so they belong to the program; the multi-window harnesses do not. **Resolved:** no, and the seam is stated as a rule for future work: **a function that aggregates over windows is a study; a function that reports on one scenario set is part of the program** (2026-07-28).
3. `examples/`: subdirectory or labels? *Proposed:* labels in `examples/README.md` plus a heading split, not a subdirectory. Moving the files breaks the README reproduction commands the project quotes, for a gain that is presentational. **Resolved:** labels and a heading split; file paths unchanged (2026-07-28).
4. Three formulation files or two? *Proposed:* three. Two would leave the evaluation semantics attached to either the model or the uncertainty representation, and they are neither; the third file is also what the studies pages link to. **Resolved:** three (2026-07-28).
5. Do figure filenames get renamed off the `example-` prefix? *Proposed:* no. They are referenced from README, specs, and ADRs, and the rename buys nothing this phase needs. **Resolved:** no; figure filenames are frozen for this phase (2026-07-28).
6. Should the ledger record test counts? *Proposed:* no. Counts rot, `conventions.md` §7 names them as the usual offender, and the README badge already carries the current one. **Resolved:** no (2026-07-28).

## Risks and rollback

**The largest risk is silent link rot.** Section anchors break invisibly: a link to a reworded heading renders fine and lands at the top of the page. `scripts/lint_docs.py` already checks cross-doc anchors, which is the main defence, so run it after every file split rather than at the end.

**The second risk is a stale module reference in a spec.** The doc linter checks that a spec's backticked dotted module paths name real modules, so moving `study.py` will fail the linter against the R2.5, R2.5b, and R2.6 specs, which name its old path. That failure is the feature working: fix those references as part of commit 1 rather than deferring them.

This spec is itself the first case. Drafting it tripped the same check on the package it proposes, which is why it names the new package by file path (`src/bess/studies/`) rather than by dotted path: a Draft that describes code not yet written cannot use the notation the linter binds to reality. Once commit 1 lands, the dotted form becomes legal here too.

**Rollback** is per commit and cheap: each is a mechanical move with a green suite on both sides, and no commit depends on a later one to be correct.

**Sequencing:** start after R2.1e is committed. The phase touches nearly every doc, so an in-flight spec would collide with it.
