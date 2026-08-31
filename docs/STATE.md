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

**No active phase.** R2.9 (interval sharpness) is implemented and closed with a
no-adoption verdict; the ledger row in [specs/README.md](specs/README.md) records what
it found. Releases 1 and 2 are complete; Release 3 has not started.

R2.9 asked whether the forecaster's quantile learners, left at LightGBM defaults since
R2.1, could be chosen for a narrower interval. It searched an exhaustive 324-config grid
per zone, selecting on tuning blocks placed in the gaps between the reporting blocks so
no day the gate scores was ever used to choose.

**Sharpness is available and the gate refused to buy it.** NL's winner is 4.5% narrower
(+6.22 EUR/MWh, 95% day-block CI [+3.17, +9.35], 57.3% of days), and its
`max_hour_deviation` rises 0.065 to 0.070: the interval is narrower at every hour, which
fixes wasteful over-coverage at 21:00 and pushes 11:00 down to 0.830. BE's winner passed
that constraint but lost pinball skill at the lower edge (0.192 to 0.196) with a width
interval reaching [+0.02, +5.68]. The two zones also chose different configurations, so
there was no single default to adopt. **Nothing in `src/bess/forecaster/forecast.py`
changed.**

Two defects in the approved design surfaced during implementation and were fixed rather
than absorbed:

- **The tuning folds were specified inside 2021**, which the reporting layout uses only
  for training. That year is the worst-calibrated in the span: at one fixed placement
  coverage runs 0.791 (2021), 0.847 (2022), 0.887 (2023), 0.897 (2024) against monthly NL
  means climbing 77 to 238 EUR/MWh. The incumbent misses the band there, so no candidate
  was feasible and the search raised. Blocks moved into the gaps between reporting
  blocks: same disjointness, plus the reporting regime and its 365-day window.
- **Ties broke on grid position**, which a property test showed is not order-invariant.
  Two configurations can score identically, and the winner then depended on how the grid
  was written. Ties now break on the cheaper model, then a canonical parameter ordering.

## Capability status

| Capability | Status | Packages |
| --- | --- | --- |
| Dispatch core | complete, gated | `assets`, `validation`, `optimizer` |
| Data feed | complete, gated | `data` |
| Backtest | complete, gated | `backtest` |
| Serving | complete, gated | `api` |
| Price forecaster | complete, gated; hyperparameters searched and left unchanged (R2.9) | `forecaster` |
| Scenario generation | complete, gated | `scenarios` |
| Stochastic dispatch | complete, gated | `stochastic`, `recourse` |
| Dispatch explainability | complete, gated | `explain` |
| Studies | three nulls reported, see [studies/](studies/) | `studies` |

---

## Next (recommended order)

1. **R3.1, imbalance-settlement recourse.** R2.7 strengthened the argument for it: the
   bid-curve delivery gap was the *only* value quantity the wider window made more
   solid, holding 4.26 to 7.91 MWh per day across four years on a 2 MWh asset, and
   nothing in the model prices it. Needs a spec; none is drafted. **Start with the data
   probe, not the spec** (CLAUDE.md §7): `entsoe-py` exposes the imbalance endpoints,
   but whether NL and BE are actually populated on them is unverified, and thin data
   should change the gate wording up front rather than be discovered late.
2. **Nothing else queued.** R2.8 is done, so every euro figure now carries both of its
   widths and no value claim is blocked on an unmeasured precision.

## Known blockers and carried findings

- **A submodule is shadowed by a same-named export.** `bess.studies.forecast_value`
  resolves to the exported *function*, not the module, so `import bess.studies.forecast_value as m`
  yields a function and attribute access on it fails. Nothing in the shipped code
  imports it that way, and it cost a debugging cycle during R2.7. Renaming either the
  function or the module would fix it; neither was in scope.
- **R1.4c stuck-feed rule does not survive long windows.** `guarded_fetch` classifies
  the NL 2021-2025 span ANOMALY/`stuck_feed` on a 5-hour run of exactly 64.00 EUR/MWh
  (2021-05-15) plus 4-hour runs at 42.30 / 140.66 / 95.60, against
  `DEFAULT_MAX_FLAT_HOURS = 4.0`. Those are ordinary merit-order flats. The nonfocal
  rule is a fixed run length applied regardless of window length, so its false-positive
  rate grows with the span; 2024 happens to contain no such run, which is why the
  year-long guard test passes. Same class of defect that forced the *focal* threshold
  from 8 hours to 24. **R2.1d and R2.7 work around it** by fetching the span unguarded
  (`span_prices` in `tests/integration/span.py`, shared by both); revisit that
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
- **The seed-width rule does not transfer to the forecaster.** R2.8 requires every new
  value claim to report its draw spread. R2.9's width claim has none, and the zero it
  measures is **structural**: LightGBM runs with `deterministic=True`, `n_jobs=1` and no
  bagging or feature subsampling, so `random_state` has no entry point into the fit. Do
  not report that 0.00 as a stability result; the day-block bootstrap is the only width a
  forecaster claim carries.
- **`max_hour_deviation` is symmetric and arguably should not be.** It scored the
  incumbent's over-coverage at 21:00 and R2.9's candidate's undercoverage at 11:00 on one
  scale, and for a battery those differ: too wide wastes opportunity, too narrow misprices
  risk. A signed rule would have reached a different verdict on NL. **Deliberately not
  changed**, because rewriting a metric after watching it reject a candidate is not a
  change the phase that watched it can make. Recorded in
  [specs/interval-sharpness.md](specs/interval-sharpness.md) for a phase that can argue
  it on its own terms.
- **Scenario-draw noise is measured, and it is not small** (R2.8, resolved). Over ten
  seeds the VSS median spans 4.85 EUR and over six the FV median spans 11.19, roughly a
  third of each study's window interval. Both published headlines were low draws, so the
  two pages now lead with the mean across seeds. **The live constraint is that the two
  widths are independent and must never be combined**, and that the draw spread is not a
  confidence interval. Any new value claim must report both widths; budget about 11 min
  per FV seed and 2.5 per VSS seed for a sweep.
- **The value-study window is settled; regime dependence is the live caveat.**
  R2.7 fixed the window at 260 days over 2022-2025. What remains open is that the
  results are strongly regime-dependent (VSS pays several times more in the 2022 crisis
  year than after it) and, on NL, no longer separable from zero. Per-year rows rest on
  about 70 windows each and sit inside their own sampling noise: the full 1705-day sweep
  contradicted a monotone-decay reading that the 52-block per-year rows appeared to
  support. Read the per-year tables with their intervals, never as a trend.
- **The `## Decisions` lint check only requires at least one such section.** The
  heading normalization left one spec with two, which the merge caught by hand. Tighten
  to "exactly one" if it recurs.
- **The doc linter's module check is a word search, not symbol resolution.**
  `_module_exists` falls back to `re.search` in the parent package's `__init__.py`, so
  a spec naming a symbol that has moved *within* a surviving package passes. This gave
  a false negative during S1 commit 1. The formulation-section check added in commit 3
  is the pattern to follow if this is tightened.
