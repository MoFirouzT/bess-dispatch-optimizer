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

**No active phase.** R2.4b (dual-grounded narration) is built, gated offline, and
**not adopted**: the endpoint exists and the adoption question is open. It turns the
R2.4 `Explanation` into prose in which the model emits placeholders and never a digit,
verified against the solved object before anything is served.

**Done.** `bess.narrate` (the six-type claim vocabulary and its predicates, the seven
rejection rules, placeholder substitution, the deterministic fallback, the provider
protocol with recorded and adversarial test doubles), `POST /explain/narrative`, the
`narrate` optional extra, and the live tier. Golden, property and unit gates written
failing first, all green. The full suite passes with `ANTHROPIC_API_KEY` unset, which
is how CI runs it.

**The first live run rejected 50 of 50, and the cause was the prompt, not the model.**
The prompt named each claim type and stated none of the conditions the verifier checks,
so the model was inferring rules like "a water-value step needs adjacent runs" and
getting them wrong. Writing the six conditions into the prompt in the verifier's own
words moved the rate to **1 rejection in 19 instances**. That 100% is an instrument
reading and it is recorded in the spec beside the corrected number, because the two are
easy to confuse later.

**The rate is 5.3% against a 5% bar at n=19, which decides nothing.** The 95% interval
runs from roughly 0.1% to 26%. The spec calls for 50 instances; that run was not
repeated after the prompt fix, by the human's decision, to avoid the spend. **The
adoption box is `- [!]`, not `- [x]`, and the endpoint does not ship until a run at the
specified size says it should.**

**A cheaper model was measured and rejected.** On the same 8 days: Opus 5 at effort low
rejected 0 and took 11.1 s median; Sonnet 5 at low rejected 2 of 8 at 6.8 s; Haiku 4.5
rejected 7 of 8 at 4.7 s, once by writing a literal digit, which is the one thing the
design forbids and the verifier caught. Opus 5 stays the default.

**The 10 s timeout was discarding correct work.** Measured latency is 9.5 to 14.8 s, so
roughly half of all good narrations were timing out. Raised to 20 s, keeping the
endpoint, on the grounds that `/explain/narrative` already solves a MILP and re-solves
an LP before it narrates and was never a fast path.

Two things surfaced that are the human's call:

- **The n=50 bar is under-powered for a 5% threshold.** A true 5% rate yields 0 to 6
  rejections in 50 draws, so a pass and a fail at that size are barely distinguishable.
  Both numbers were fixed in the spec before any data existed, which was the right
  order; the observation is that the instrument cannot resolve the question it was
  pointed at. Raising n or widening the bar is a spec amendment and should be argued
  on its own, not after seeing a result.
- **`max_tokens` 2048 is too small once thinking is on.** Every failure in the Sonnet 5
  high-effort arm was a truncated-JSON parse error rather than a bad claim. It does not
  bite at `effort: low`, which is the shipped setting, so nothing was changed.

Releases 1 and 2 are otherwise complete; Release 3 has not started.

**Presentation pass (2026-09-01), outside the phase ladder.** The README was cut from
278 lines to 153: the headline numbers and the quickstart now sit above the fold, and
the full results narrative, every figure, and the scope limits moved verbatim to
[results.md](results.md), which is now their canonical home. The baseline table lives
in the README only, and `results.md` points at it (charter rule 1). Added
`examples/quickstart.py`, a front-door script that runs the whole stack on the **base
install** in about two seconds: no ENTSO-E token, no optional dependency group, no
plotting. Its smoke test is deliberately its own module,
`tests/unit/test_quickstart_smoke.py`, because `test_examples_smoke.py` skips whenever
matplotlib is absent, which is exactly the base CI job the quickstart claims to run in.
No source, math, or gate changed.

**Resolution claim corrected (2026-09-01).** `conventions.md` §1 said the backtest and
all downstream work run on the native 15-minute series at `Δt = 0.25`. They do not, and
never did: every committed study and example passes `dt=1.0` on a window that closes
before the 2025-10-01 SDAC switch, when the published series was hourly. The wording now
says that, and says it is a fact about the data rather than a limit of the model. This
aligns the doc with [day-ahead is 15-minute native](decisions/day-ahead-15min-native.md),
which was already correct, so it is a correction and not a new decision.

**What was untested is now gated.** The hypothesis cases draw `Δt` from {0.25, 0.5, 1.0}
over plain sequences, so the arithmetic was covered, but the seam a real quarter-hourly
feed goes through was not: a tz-aware `15min` index grouped into calendar-day windows of
96. `synthetic_day_ahead` gained a `freq` argument (`"1h"` default, bit-identical;
`"15min"` holds each hourly price across its four quarters), and
`test_backtest.py::test_resolution_invariance_*` solves the same prices at both
resolutions and requires the same revenue and the same MWh cycled. **Revenue alone is a
soft check**: capacity and the terminal-SoC target cap the daily cycle either way, so
solving quarter-hourly data at `dt=1.0` still lands within about 0.5%. The energy cycled
comes out roughly 4x too small, which is the assertion that bites.

**Still open: the 15-minute economics.** The fixture's quarter-hourly form carries no
intra-hour spread by construction, so it proves the plumbing and measures nothing. Real
intra-hour spread should raise the arbitrage ceiling and change where the ramp limit
binds, and that needs post-2025-10 prices from the live API. Blocked with the outage
below.

## Capability status

| Capability | Status | Packages |
| --- | --- | --- |
| Dispatch core | complete, gated | `assets`, `validation`, `optimizer` |
| Data feed | complete, gated | `data` |
| Backtest | complete, gated | `backtest` |
| Serving | complete, gated | `api` |
| Price forecaster | complete, gated; hyperparameters searched and left unchanged (R2.1f), drift-robust calibration built and not adopted (R2.1g) | `forecaster` |
| Scenario generation | complete, gated | `scenarios` |
| Stochastic dispatch | complete, gated | `stochastic`, `recourse` |
| Dispatch explainability | complete, gated | `explain` |
| Dispatch narration | built and gated offline, **not adopted** (R2.4b); live rejection rate 5.3% at n=19 against a 5% bar, undecided | `narrate` |
| Dispatch narration | built and gated offline; not adopted, live tier unrun | `narrate` |
| Studies | nine pages, four nulls reported, see [studies/](studies/) | `studies` |

---

## Next (recommended order)

1. **R3.1, imbalance-settlement recourse.** R2.7 strengthened the argument for it: the
   bid-curve delivery gap was the *only* value quantity the wider window made more
   solid, holding 4.26 to 7.91 MWh per day across four years on a 2 MWh asset, and
   nothing in the model prices it. Needs a spec; none is drafted. **Start with the data
   probe, not the spec** (CLAUDE.md §7): `entsoe-py` exposes the imbalance endpoints,
   but whether NL and BE are actually populated on them is unverified, and thin data
   should change the gate wording up front rather than be discovered late.
2. **Refit cadence, from R2.1g's null.** The largest coverage effect this project has
   measured on the forecaster is not a calibration construction, it is how often the model
   is refit: annual to monthly is worth +0.18 coverage on the NL 2022 crisis year and a
   35% narrower interval. R2.1g could not adopt it (a scheduling change is not a
   calibration change and was not in its scope) and deliberately did not. Needs a spec.
   **The obvious trap is that "refit more often" has a cost nobody here has measured**:
   fit time, and whether a model refit on a short recent window loses the crisis history
   R2.1e found is useful under a de-levelled target.
3. **Run R2.4b's live tier.** One command with an `ANTHROPIC_API_KEY` set:
   `uv run pytest tests/integration/test_narration_live.py -q -s`. It is 50 model calls
   and it decides whether the narrative endpoint ships. Above the 5% bar the endpoint
   comes out, the verifier and fallback stay, and the rate is the finding. Do not tune
   the prompt to get under the bar; that is out of scope in the spec for a reason.
4. **Nothing else queued.** R2.8 is done, so every euro figure now carries both of its
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
  **Update 2026-09-01:** the Transparency Platform is migrating to new infrastructure on
  **2026-09-02**, and website downloads are capped at 30 days until it completes. Treat the
  live path as unavailable through the migration and re-probe from 2026-09-03. Nothing has
  fetched against the new infrastructure yet, so the 49 token-gated tests are the first
  thing to run afterwards, and a real sample gets printed before any new code is written
  against it (CLAUDE.md §7). Both the R3.1 imbalance probe and the 15-minute economics run
  wait on this.
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
