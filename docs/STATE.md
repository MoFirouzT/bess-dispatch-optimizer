# STATE: session continuity

Read this first (after `CLAUDE.md`), update it at the end of every working session.
Holds: current phase · capability status · what's next · known blockers.

**History is not here.** What each phase concluded is one row per phase in the
[phase ledger](specs/README.md); the reasoning behind each is in that phase's spec,
under Decisions. This file stays short on purpose: it is rewritten every
session, so an append-only record inside it grows without bound, which is what
happened before 2026-07-28.

---

## Current phase

**No active phase.** Releases 1 and 2 are complete; Release 3 has not started.

The capability restructure is implemented and committed, in four commits: the
`bess.studies` extraction, the studies doc shelf, the vocabulary plus formulation
recut, and the decision-record consolidation (26 numbered ADRs to 17 subject-named
records). Its work order has been retired now that the restructure is done; the
rules it established live in [architecture.md](architecture.md),
[decisions/README.md](decisions/README.md) and [specs/README.md](specs/README.md), and
the ledger row records what it did.
Its governing invariant, that **no number moves**, was verified mechanically rather
than by eye: numeric literals and definition bodies for the code move, and
byte-identical section bodies for the formulation recut.

**The spec consolidation is done, and uncommitted.** The same principle applied to
`docs/specs/`: where a phase boundary recorded *when* work happened rather than a
design decision, the work orders merged. Three merges landed (`dispatch-core`,
`data-feed`, `price-forecaster`), every remaining spec dropped its phase ID from its
filename, and the restructure's own work order was retired. **21 specs to 15.**

Each merge was verified by diffing the set of distinct numeric values before and
after, which caught seven real losses that were then restored. Phase IDs survive in a
`**Phases:**` line on every spec, which is what keeps the `Depends on:` graph resolving
after a rename or a merge.

Full suite 373 passed / 29 skipped; ruff/format/mypy(48)/lint-imports(**5** KEPT,
the new one forbidding the serving chain from importing `bess.studies`)/docs-lint(54)
all clean. The full **live** gate also passed, 29 tests, 16 minutes.

## Capability status

| Capability | Status | Packages |
| --- | --- | --- |
| Dispatch core | complete, gated | `assets`, `validation`, `optimizer` |
| Data feed | complete, gated | `data` |
| Backtest | complete, gated | `backtest` |
| Serving | complete, gated | `api` |
| Price forecaster | complete, gated | `forecaster` |
| Scenario generation | complete, gated | `scenarios` |
| Stochastic dispatch | complete, gated | `stochastic`, `recourse` |
| Dispatch explainability | complete, gated | `explain` |
| Studies | three nulls reported, see [studies/](studies/) | `studies` |

---

## Next (recommended order)

1. **Re-window the value studies properly.** Partially addressed: the live gate runs
   Mar-Jun 2024 (94 windows) and those measurements are now what the studies pages
   publish, replacing an older Q2-only 63-window set. But all three nulls still rest
   on a single 2024 window. R2.1d built the instrument (`rolling_origin_folds` over
   2021-01-01..2025-09-30, 1734 days), and applying it one level up is still the
   change most likely to move a headline claim. Needs its own spec; none is drafted.
2. **Release 3**, phase ids in `planning/` (Tier 0): R3.1 imbalance-settlement
   recourse, R3.2 grid-connection cap, R3.3 ancillary co-optimization, R3.4 price
   impact. R2.6's own result argues for **R3.1**: it measured a delivery gap of 4 to
   8 MWh per day on a 2 MWh asset and left it unpriced.

## Known blockers and carried findings

- **R1.4c stuck-feed rule does not survive long windows.** `guarded_fetch` classifies
  the NL 2021-2025 span ANOMALY/`stuck_feed` on a 5-hour run of exactly 64.00 EUR/MWh
  (2021-05-15) plus 4-hour runs at 42.30 / 140.66 / 95.60, against
  `DEFAULT_MAX_FLAT_HOURS = 4.0`. Those are ordinary merit-order flats. The nonfocal
  rule is a fixed run length applied regardless of window length, so its false-positive
  rate grows with the span; 2024 happens to contain no such run, which is why the
  year-long guard test passes. Same class of defect that forced the *focal* threshold
  from 8 hours to 24. **R2.1d works around it** by fetching the span unguarded
  (`_span_prices` in `tests/integration/test_forecaster_live.py`); revisit that
  workaround once the rule is fixed. **Do not simply raise the constant.**
- **Two governing references named from memory and NOT verified**, so both phases ship
  ungoverned and `references.md` is deliberately unwritten for them (CLAUDE.md §1):
  Lago, Marcjasz, De Schutter & Weron (Applied Energy, 2021) for R2.1d's walk-forward
  protocol, and Lei, G'Sell, Rinaldo, Tibshirani & Wasserman (JASA, 2018) for R2.1e's
  locally-weighted conformal. Neither phase depends on either. The R2.6 candidates
  (Fleten & Kristoffersen; Loehndorf & Wozabal) are unverified on the same terms.
- **`_net_to_pair` is imported across a package boundary.** `bess.studies` reads this
  private helper from `bess.stochastic.vss`. It was an intra-package private import
  before S1 moved the studies out, and the move made it worse rather than introducing
  it. Promoting it is a small follow-up, deliberately not folded into a phase whose
  invariant is that nothing changes.
- **The value-study numbers are window-sensitive, and the window is not settled.**
  On Mar-Jun 2024 (94 windows) the VSS median is +12.90 EUR with 66% of windows
  positive; forecast value is −19.81 EUR with 41% positive. On the Q2-only slice the
  project published before (63 windows) the same quantities read +12 / 62% and
  −0.9 / 49%. VSS is robust across both; **forecast value is not**, so its "centred on
  zero" framing was weakened to "null, and if anything mildly negative". Whether
  Mar-Jun is the right authoritative window is an open question, not a settled one.
- **The `## Decisions` lint check only requires at least one such section.** The
  heading normalization left one spec with two, which the merge caught by hand. Tighten
  to "exactly one" if it recurs.
- **The doc linter's module check is a word search, not symbol resolution.**
  `_module_exists` falls back to `re.search` in the parent package's `__init__.py`, so
  a spec naming a symbol that has moved *within* a surviving package passes. This gave
  a false negative during S1 commit 1. The formulation-section check added in commit 3
  is the pattern to follow if this is tightened.
