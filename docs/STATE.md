# STATE: closing state

Where the project stands now that it is finished at its scope:
what exists, what each capability's status is,
the findings no phase owns, and what a successor would pick up first.

*Assumes:*
the capability map in [architecture.md](architecture.md);
the per-phase record in the [phase ledger](specs/README.md).

**History is not here.**
What each phase concluded is one row per phase in the ledger,
the reasoning behind each is in that phase's spec under *Decisions*,
and the reader-facing findings are in [studies/](studies/README.md).
This file holds only what is still live.

---

## Status

**Finished at scope. No phase is active and none is planned.**

Releases 1 and 2 are complete.
Eight capabilities are built and gated by golden and property tests;
a ninth, dispatch narration, is built and gated offline and is not adopted.
Nine studies are published, including the nulls.
Release 3 was scoped and not started.

Two questions are open and each is recorded below rather than closed by default:
the drift-robust calibration arms clear their bar and are not adopted,
and the stuck-feed rule has a known false-positive mode on long windows.
A third was settled on 2026-09-04: the narration endpoint failed its acceptance gate and does not ship.
None of them blocks anything that ships;
all three are things a successor should read before touching the module they sit in.

## Capability status

| Capability | Status | Packages |
| --- | --- | --- |
| Dispatch core | complete, gated | `assets`, `validation`, `optimizer` |
| Data feed | complete, gated; carried defect in the stuck-feed rule, below | `data` |
| Backtest | complete, gated | `backtest` |
| Serving | complete, gated | `api` |
| Price forecaster | complete, gated; hyperparameters searched and left unchanged (R2.1f); drift-robust calibration built, clears its bar, **not adopted** (R2.1g), below | `forecaster` |
| Scenario generation | complete, gated | `scenarios` |
| Stochastic dispatch | complete, gated | `stochastic`, `recourse` |
| Dispatch explainability | complete, gated | `explain` |
| Dispatch narration | built and gated offline, **not adopted** (R2.4b); the acceptance gate ran at n=50 on 2026-09-04 and rejected 22.0% against a 5% bar, so the endpoint does not ship | `narrate` |
| Studies | nine pages, see [studies/](studies/README.md) | `studies` |

---

## Adoption decisions

Two capabilities were built, measured, and deliberately not adopted.
The first is still open and a successor should settle it before changing the forecaster;
the second is closed and what is left of it is a removal.

### R2.1g: the arms clear their bar, and adoption waits on the refit cadence

The R2.1g result was re-scored on 2026-09-03 and **the recorded null inverted**.
The committed gate and the recorded gate numbers were two different experiments:
the test ran `refit_every_days=365` on the extended span
while every recorded number was measured at a monthly refit on the shorter span.
Re-run monthly on the extended span,
the baseline lands inside the band in both zones
and the composed arm adds **+0.146 NL and +0.150 BE** worst-year coverage against a +0.03 bar,
where the recorded run read +0.019 and nothing.
The amendment is in [the spec](specs/drift-robust-conformal.md) and the write-up is in [the study](studies/drift-robust-conformal.md).

**Nothing in `src/` changed and adoption is deliberately not taken.**
`refit_every_days` lives only in the evaluation harness;
nothing in the serving path schedules a refit,
and the same arm clamps 71.6% of days and fails outright at an annual one.
Adopting now would ship a default whose benefit rests on an operating discipline this repo does not implement.
**So the refit cadence is R2.1g's precondition, not a follow-on:** settle it, re-score, then adopt if the arm still clears.
The cost nobody here has measured is fit time,
and whether a model refit on a short recent window loses the crisis history R2.1e found useful under a de-levelled target.

The reader-facing documents were reconciled with this on 2026-09-04:
the R2.1g ledger row, the null count in the README and in `studies/README.md`,
and the drift-robust paragraph in `results.md`.
Three studies came back null, not four.

### R2.4b: the narration endpoint does not ship

**Settled on 2026-09-04.**
The live tier ran at its specified 50 instances against a real model and rejected **11 of 50, 22.0%**,
against the 5% bar the spec fixed before the first live call.
So `POST /explain/narrative` does not ship.
The verifier, the deterministic fallback and the offline gates stay,
and the rate is the finding: on this task, constrained generation under a whole-response check did not reach the quality the phase set for it.
The n=19 reading of 5.3% had a 95% interval of roughly 0.1% to 26%, and the larger sample landed near the top of it.

**The endpoint was removed on 2026-09-04**, which is what a failed gate calls for:
the `POST /explain/narrative` route and `NarrativeResponse`, its two route tests, and the README, architecture and `.env.example` lines that described it.
The `bess.narrate` package itself stays.
It is the phase's own record of what was built and measured, its offline gates are green, and the layering contract still pins it above `explain` so that layer cannot acquire a network call.
`api` no longer imports it, and the `narrate` extra stays so the live tier can be re-run.

The run also found **a defect in the gate rather than in the design**.
`test_a_verified_narration_contains_no_number_the_model_wrote` omitted state of charge from its set of sourced tokens,
so it rejected a correct narration on `2.000`, a value the solver produced and the renderer substituted.
Rule 1 forbids the model from writing a literal digit outside a placeholder, so that token could not have come from the model.
The oracle now covers every placeholder the renderer can emit.

One thing was noted before the run and did not bind on it:
**the n=50 bar is under-powered for a 5% threshold**, since a true 5% rate yields 0 to 6 rejections in 50.
Eleven is far outside that range, so the under-powering would only have mattered had the answer been close.

---

## Carried findings no phase owns

Defects and gaps that are real, are not blocking anything, and belong to no phase.
A finding already written down where it belongs does not repeat here:
results live in the [phase ledger](specs/README.md) and the study pages,
caveats about a measurement live in the spec that made it,
and unverified sources live in [references.md](references.md).

- **The R1.4c stuck-feed rule does not survive long windows.**
  `guarded_fetch` classifies the NL 2021 to 2025 span ANOMALY/`stuck_feed`
  on a 5-hour run of exactly 64.00 EUR/MWh (2021-05-15) plus 4-hour runs at 42.30 / 140.66 / 95.60,
  against `DEFAULT_MAX_FLAT_HOURS = 4.0`.
  Those are ordinary merit-order flats.
  The nonfocal rule is a fixed run length applied regardless of window length,
  so its false-positive rate grows with the span;
  2024 happens to contain no such run, which is why the year-long guard test passes.
  Same class of defect that forced the *focal* threshold from 8 hours to 24.
  R2.1d and R2.7 work around it by fetching the span unguarded
  (`span_prices` in `tests/integration/span.py`, shared by both);
  revisit that workaround once the rule is fixed.
  **Do not simply raise the constant.**

- **Two small code follow-ups in `bess.studies`, neither blocking anything.**
  `bess.studies.forecast_value` resolves to the exported *function*, not the module,
  so `import bess.studies.forecast_value as m` yields a function and attribute access on it fails;
  nothing shipped imports it that way, and it cost a debugging cycle during R2.7.
  Separately, `bess.studies` reads the private `_net_to_pair` from `bess.stochastic.vss` across a package boundary;
  the S1 split made an intra-package private import worse rather than introducing it.
  Renaming the one and promoting the other are both small,
  and both were left out of phases whose invariant was that nothing changes.

- **The 15-minute economics are unmeasured.**
  The plumbing is gated: `synthetic_day_ahead` takes a `freq` argument
  and `test_backtest.py::test_resolution_invariance_*` solves the same prices at both resolutions,
  requiring the same revenue and the same MWh cycled.
  But the fixture's quarter-hourly form carries no intra-hour spread by construction,
  so it proves the seam and measures nothing.
  Real intra-hour spread should raise the arbitrage ceiling and change where the ramp limit binds,
  and that needs post-2025-10 prices from the live API.
  The fetch path works and nothing has been run against them.

- **Every committed study and example runs hourly, at `dt = 1.0`.**
  Each closes before the 2025-10-01 SDAC switch, when the published series was hourly.
  This is a fact about the data rather than a limit of the model;
  `conventions.md` §1 says so, aligned with [day-ahead is 15-minute native](decisions/day-ahead-15min-native.md).

---

## What a successor would pick up

In the order the measurements argue for.

1. **Refit cadence for the forecaster.**
   The largest coverage effect this project has measured is not a calibration construction, it is how often the model is refit:
   annual to monthly is worth +0.18 on the NL 2022 crisis year, **+0.34 on 2021**, and a 35% narrower interval.
   It now blocks R2.1g's adoption.
   Needs a spec.

2. **R3.1, imbalance-settlement recourse.**
   R2.7 strengthened the argument for it:
   the bid-curve delivery gap was the *only* value quantity the wider window made more solid,
   holding 4.26 to 7.91 MWh per day across four years on a 2 MWh asset, and nothing in the model prices it.
   Needs a spec; none is drafted.

   **The data probe was run (2026-09-03) and it does not kill the phase.**
   Its four answers, to be written into the spec before its gate:
   *Populated?* Yes, `query_imbalance_prices` returns data for both zones in every window tried.
   *Schema?* Both zones come back the same shape, two float columns named `Long` and `Short`.
   That is **not** what `market_reference.md` §6 predicts
   (NL a single price with corrections, BE a single price plus an alpha component).
   The two columns are equal in most settlement periods and diverge in others,
   NL 2024-04-01 00:00 being Long -40.00 against Short 1988.17.
   Reconcile the doc with what `entsoe-py` actually returns before the gate is worded;
   the probe deliberately does not judge which is right.
   *Resolution?* 15 minutes, in every window including 2022,
   so the settlement period was always quarter-hourly and does not depend on the 2025-10 day-ahead switch.
   *How far back?* At least 2019-01-01 for both zones at 15 minutes,
   checked beyond the script's own windows, which stop at 2022-08.
   **The gate question is answered: the record spans every day the 2022 to 2025 value studies score.**

   One gap to design around:
   NL `query_imbalance_volumes` raises `NoMatchingDataError` on every historical window and works only on the recent one,
   while BE has it throughout.
   NL volume history is reachable only through `query_current_balancing_state`, which is 1-minute rather than the 15-minute settlement period.

3. **Nothing else is queued.** Every phase is closed, every adoption question has an answer or a named precondition, and the serving surface matches the record.
