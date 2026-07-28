# STATE: session continuity

Read this first (after `CLAUDE.md`), update it at the end of every working session.
Holds: current phase · capability status · what's next · known blockers.

**History is not here.** What each phase concluded is one row per phase in the
[phase ledger](specs/README.md); the reasoning behind each is in that phase's spec,
under Open questions. This file stays short on purpose: it is rewritten every
session, so an append-only record inside it grows without bound, which is what
happened before 2026-07-28.

---

## Current phase

**S1 capability restructure, in progress.** Spec:
[`specs/S1-capability-restructure.md`](specs/S1-capability-restructure.md), Approved
and frozen 2026-07-28, six open questions resolved as proposed.

Commits 1 and 2 are done and committed; commit 3 (vocabulary, formulation recut,
this ledger) is in the working tree. The phase's governing invariant is that **no
number moves**, verified for commit 1 by comparing numeric literals and definition
bodies before and after the move.

Releases 1 and 2 are complete. Release 3 has not started.

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
| Studies | four nulls reported, see [studies/](studies/) | `studies` |

---

## Next (recommended order)

1. **Finish S1.** Commit 3 is in the tree; the remaining work is the README
   capability list and the stale test badge.
2. **Re-window the value studies.** R2.5, R2.5b and R2.6 all still rest on NL
   Mar-Jun 2024, so all three headline nulls are single-sample. R2.1d built the
   instrument to fix this (`rolling_origin_folds` over 2021-01-01..2025-09-30, 1734
   days), and applying it one level up is the change most likely to move a headline
   claim in this project. Needs its own spec; none is drafted.
3. **Release 3**, phase ids in `planning/` (Tier 0): R3.1 imbalance-settlement
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
- **The doc linter's module check is a word search, not symbol resolution.**
  `_module_exists` falls back to `re.search` in the parent package's `__init__.py`, so
  a spec naming a symbol that has moved *within* a surviving package passes. This gave
  a false negative during S1 commit 1. The formulation-section check added in commit 3
  is the pattern to follow if this is tightened.
