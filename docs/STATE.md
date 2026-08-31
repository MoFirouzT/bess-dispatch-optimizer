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

**R2.1g, drift-robust conformal intervals.** Spec approved, machinery built and gated,
**not yet measured on real prices**. It replaces the conformal calibration step with two
published constructions that survive a regime shift: a weighted quantile over the
calibration scores (Barber et al. 2023) and an online update of the target level (Gibbs
and Candès 2021). This is the phase that answers what R2.1b only detects and R2.1f only
measured, the coverage decay from 0.897 in 2024 to 0.791 across the 2021 ramp.

**Done.** `conformal.py` (weights, the weighted quantile with its `+inf` atom, both
scores, the two Theorem 2a gap bounds, the ACI recursion and its two bounds);
`weight_half_life_days` and an `alpha` override threaded through `PriceForecaster`;
`sequential_coverage`, the online harness the block harness cannot stand in for. Golden,
property and unit gates all green, written failing first.

Also done since: the seeded drift regimes (`synthetic_drift`, four of them, the fourth
being volatility drift, which is the only case that separates what the two arms repair);
knob selection on those regimes; `EXTENDED_SPAN` starting 2019-01-01 beside an untouched
`SPAN`; and the live gate module, written and collecting but never run.

**Knob selection is settled, and it did not pick the arm the phase was pitched on.** Selected:
**half-life `None`, gamma 0.005**, that is ACI alone, the only arm feasible on all four
regimes (coverage in band and clamp under 5% everywhere). It lifts the worst regime from
0.785 to 0.852 at **+0.1%** width on calm data, because it widens only when it is
missing. Full write-up in [studies/drift-robust-conformal](studies/drift-robust-conformal.md).

**Not done.** The real-data run on NL and BE, and the ledger row. No adoption decision
exists yet and no shipped default has changed.

Three things surfaced during the build. The first two are the human's call:

- **The shipped CQR interval is not the one the formulation describes.**
  `formulation-uncertainty.md` §R2.1 defines one signed score and one margin applied to
  both bounds; MAPIE's `predict_interval` defaults to `symmetric_correction=False`, a
  separate constant per side, which is what has run since R2.1. Our implementation
  matches MAPIE's *symmetric* correction to 0.0 on both bounds, so the divergence is
  entirely between the default and the documentation, and it is CQR-only. No coverage
  number is wrong: both are valid constructions with the same marginal guarantee, which
  is why four phases of gates passed either way. Pinned by
  `test_the_shipped_default_is_the_asymmetric_variant_not_the_documented_one`. The spec
  proposes changing the code, in a separate change, since it moves shipped numbers.
- **Clamping the ACI level is worse than the approved spec said.** It does not pause the
  long-run guarantee, it removes the saturation feedback the guarantee rests on, so the
  iterate can diverge and the published bound does not return when the clamp stops
  binding. Found by a property test on adversarial sequences before any data was touched.
  The gate now reads the exact telescoping identity, which survives clamping, and the
  clamp binding rate stays capped at 5%.
- **The weighted arm's bound and its variance pull against each other.** A shorter
  half-life tightens the Theorem 2a coverage-gap bound and shrinks the effective sample
  that estimates the margin: at a 3-day half-life about 104 points survive out of 814, so
  the 90% quantile rests on roughly ten effective tail observations. Measured, the margin
  swung -40% to +18% across three refits of one run, and the swings cancel over a run, so
  the arm moves coverage far less reliably than it looks like it should. **Theorem 2a
  bounds the first effect and says nothing about the second**, so a half-life chosen to
  make the bound look good buys a noisier interval without warning. The arm stays in the
  real run anyway, because it is the only one that yields a stated number.

Releases 1 and 2 are otherwise complete; Release 3 has not started.

## Capability status

| Capability | Status | Packages |
| --- | --- | --- |
| Dispatch core | complete, gated | `assets`, `validation`, `optimizer` |
| Data feed | complete, gated | `data` |
| Backtest | complete, gated | `backtest` |
| Serving | complete, gated | `api` |
| Price forecaster | complete, gated; hyperparameters searched and left unchanged (R2.1f) | `forecaster` |
| Scenario generation | complete, gated | `scenarios` |
| Stochastic dispatch | complete, gated | `stochastic`, `recourse` |
| Dispatch explainability | complete, gated | `explain` |
| Studies | three nulls reported, plus one interim page awaiting data, see [studies/](studies/) | `studies` |

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

- **The ENTSO-E API was down and the study path has no fallback.** Every request
  returned 503 across 13 minutes of probing, endpoint-wide: an unauthenticated request
  got the same, and the transparency portal stayed up, so it was a partial outage on
  their side rather than a token or quota problem. This blocks R2.1g's data extension and
  its real-data run, and nothing else. Worth noting that `span_prices` and
  `extended_span_prices` deliberately bypass `guarded_fetch` for the R1.4c reason below,
  so a study fetch during an outage simply raises: the project's circuit breaker does not
  cover the path that most needs a long fetch to succeed.
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
  value claim to report its draw spread. R2.1f's width claim has none, and the zero it
  measures is **structural**: LightGBM runs with `deterministic=True`, `n_jobs=1` and no
  bagging or feature subsampling, so `random_state` has no entry point into the fit. Do
  not report that 0.00 as a stability result; the day-block bootstrap is the only width a
  forecaster claim carries.
- **`max_hour_deviation` is symmetric and arguably should not be.** It scored the
  incumbent's over-coverage at 21:00 and R2.1f's candidate's undercoverage at 11:00 on one
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
