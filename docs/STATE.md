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

**R2.7 (study windowing) is implemented**; the ledger row in
[specs/README.md](specs/README.md) records what it found. **R2.8 (draw noise) is
drafted and scaffolded**, with its measurement not yet run: see below. Releases 1 and 2
are otherwise complete; Release 3 has not started.

R2.7 re-measured all four euro value studies on 260 delivery days in 52 blocks over
2022-01-01 to 2025-09-29, reusing R2.1d's fold layout verbatim so the euros and the
forecaster's pinball skill are scored on the identical days, with the two headline
studies repeated on BE.

**The three nulls hardened and the one positive result shrank.** VSS falls from the
published +12.90 to **+3.56 on NL**, whose interval now includes zero, while **BE holds
at +8.36** with an interval above it. Forecast value stays null in both markets and less
negative than published. Tail value and bid-curve value are null in every year and at
every recourse budget. The unpriced delivery gap (4.26 to 7.91 MWh per day on a 2 MWh
asset) was the only quantity the wider window strengthened.

Two defects surfaced and were fixed rather than absorbed:

- **Windows were seeded by their position in the series**, so the same delivery day
  scored inside a 4-month and a 4.7-year series gave different answers. Seeds now derive
  from `(seed, window date)`, which makes selection a filter: scoring a subset returns
  exactly what scoring everything and discarding the rest returns, gated bitwise. About
  4 EUR of the VSS drop is this, the rest is the window.
- **The per-year block labeller compared `asi8` integers against a nanosecond
  constant** while the index carried microsecond resolution, marking every day a block
  boundary. Caught by a golden oracle.

Prior structural work (the capability restructure and the spec consolidation) is
implemented and committed; its rules live in [architecture.md](architecture.md),
[decisions/README.md](decisions/README.md) and [specs/README.md](specs/README.md).

Full suite 404 passed / 40 skipped; ruff, format, mypy(49), lint-imports (**5** KEPT),
docs-lint(55) all clean. The R2.7 live gates passed on both zones; the studies tier is
marked `studies` and deselected from the routine live run because it takes about an
hour.

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

1. **R3.1, imbalance-settlement recourse.** R2.7 strengthened the argument for it: the
   bid-curve delivery gap was the *only* value quantity the wider window made more
   solid, holding 4.26 to 7.91 MWh per day across four years on a 2 MWh asset, and
   nothing in the model prices it. Needs a spec; none is drafted. **Start with the data
   probe, not the spec** (CLAUDE.md §7): `entsoe-py` exposes the imbalance endpoints,
   but whether NL and BE are actually populated on them is unverified, and thin data
   should change the gate wording up front rather than be discovered late.
2. **Finish R2.8** ([specs/draw-noise.md](specs/draw-noise.md)), which is drafted and
   scaffolded but **not measured**. The helper, golden and property gates, and the live
   reported test are in; what remains is running it (10 VSS seeds and 6 FV seeds over
   R2.7's window set, about 70 minutes under `uv run pytest -m "integration and studies"`),
   recording the widths in the spec, and publishing them beside the window intervals on
   the two studies pages. Its spec boxes are deliberately unticked until then.

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
- **Scenario-draw noise is unquantified, and it is not small.** R2.7 measured that
  changing only *which* bootstrap draws land on which day, holding protocol, window,
  asset and data fixed, moved the published VSS median by about 4 EUR on a claim of
  +12.90. Neither draw is more correct: both are valid samples from the same 30-path
  bootstrap. Window sampling is now covered by the reported intervals; **draw noise is
  covered by nothing**, so every euro figure in [studies/](studies/) has a precision
  nobody has measured. Quantifying it means re-running the studies across many seeds,
  which R2.7 kept out of scope to hold one variable. Do this before any phase reports a
  tighter value claim.
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
