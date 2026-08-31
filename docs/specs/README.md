# Specs and the phase ledger

Each phase of this project was built from a frozen work order in this directory:
scope, interfaces, and the golden/property test contract, reviewed before any code
was written. This file indexes them and records what each phase concluded.

*Assumes: the capability map in [architecture.md](../architecture.md); the workflow
in [CLAUDE.md](../../CLAUDE.md) §3.*

---

## Phase IDs and capabilities

The `R<n>.<m>` IDs are **delivery labels**, not architecture. They record the order
things were built, including the letter suffixes that mark a defect found and fixed
later. Reader-facing documents name capabilities instead; the IDs survive here and in
git history, where chronology is the point.

This is also the index of the documents in this directory. Filenames name their
subject, so a capability delivered over several phases has one spec, and a capability
whose later phases answered a different question has several.

| Capability | Specs | Phases | Packages |
| --- | --- | --- | --- |
| Dispatch core | [dispatch-core](dispatch-core.md) | R1.1, R1.2, R1.3 | `bess.assets`, `bess.validation`, `bess.optimizer` |
| Data feed | [data-feed](data-feed.md) | R1.4b, R1.4c | `bess.data` |
| Backtest | [backtest](backtest.md) | R1.4a | `bess.backtest` |
| Serving | [serving](serving.md) | R1.5 | `bess.api` |
| Price forecaster | [price-forecaster](price-forecaster.md), [forecaster-evaluation](forecaster-evaluation.md), [target-normalization](target-normalization.md) | R2.1, R2.1b, R2.1c / R2.1d / R2.1e | `bess.forecaster` |
| Scenario generation | [scenario-generation](scenario-generation.md), [scenario-tail](scenario-tail.md), [scenario-tail-conditioning](scenario-tail-conditioning.md) | R2.2 / R2.2b / R2.2c | `bess.scenarios` |
| Stochastic dispatch | [stochastic-dispatch](stochastic-dispatch.md) | R2.3 | `bess.stochastic`, `bess.recourse` |
| Dispatch explainability | [explainability](explainability.md) | R2.4 | `bess.explain` |
| (studies, not a capability) | [value-evaluation](value-evaluation.md), [tail-dispatch-value](tail-dispatch-value.md), [bid-curves](bid-curves.md), [study-windowing](study-windowing.md), [draw-noise](draw-noise.md) | R2.5 / R2.5b / R2.6 / R2.7 / R2.8 | `bess.studies` |

A slash in the **Phases** column separates the phases owned by each spec, in the same
order as the **Specs** column beside it; a comma lists phases sharing one spec.

## In flight

Approved-but-unbuilt and draft specs live here too, and are listed separately because
they carry no ledger row: a row records what a phase found, and an unbuilt phase has
found nothing.

| Spec | Status | What it will settle |
| --- | --- | --- |
| [interval-sharpness](interval-sharpness.md) | Approved, in build (R2.9) | Whether the forecaster's quantile learners, whose hyperparameters were left at library defaults, can be chosen for a narrower interval without giving up coverage or per-hour calibration |

---

## The ledger

One row per phase, oldest first. Dates are the implementing commit's date. The
**finding** column is the point: what the phase established, including when the
answer was "no".

Several rows link to the same spec. Where a capability was delivered in passes
whose boundaries recorded *when* work happened rather than a design decision, the
work orders were merged into one document and the rows still record the sequence.

| Phase | Date | Capability | What changed | Finding |
| --- | --- | --- | --- | --- |
| [R1.1](dispatch-core.md) | 2026-06-24 | Dispatch core | the deterministic MILP: physics, mutual exclusion, terminal SoC | Grid-side metering locked as the correctness trap: efficiency lives in the SoC balance and never in the objective |
| [R1.2](dispatch-core.md) | 2026-06-25 | Dispatch core | wear as a cost subtracted from the objective | Regrounded on 2026-07-13: the original convex-PWL cost was self-derived and matched no source, replaced by the published linear DoD-stress case, which is also step-size invariant |
| [R1.3](dispatch-core.md) | 2026-06-26 | Dispatch core | closed-form feasibility test ahead of the solver | Adds no math: the conditions are algebraic corollaries of R1.1. Ramp-free reachability is necessary and sufficient; with ramp it stays a sound filter only |
| [R1.4a](backtest.md) | 2026-06-26 | Backtest | three revenue quantities and a leakage boundary | The ordering is provable, so it gates. On real NL a no-look-ahead rolling policy captures ~99% of the perfect-foresight ceiling: the deterministic problem is essentially solved, and the value left is uncertainty |
| [R1.4b](data-feed.md) | 2026-06-26 | Data feed | live ENTSO-E day-ahead loader (BE/NL) | Schema fetched and inspected before coding against it. The parquet cache built here went unused until 2026-07-26, when it was switched on |
| [R1.5](serving.md) | 2026-06-26 | Serving | FastAPI dispatch service with a solver circuit breaker | Availability is the contract: a solver timeout serves the greedy schedule rather than failing the request |
| [R1.4c](data-feed.md) | 2026-07-01 | Data feed | a second circuit breaker, on the data feed | A stale price is more dangerous than an obvious outage, because it fails silently. The stuck-feed check keys on a repeated *arbitrary* value, not a focal one: the market really does clear at exactly €0.00 for hours on end |
| [R2.1](price-forecaster.md) | 2026-07-01 | Price forecaster | LightGBM quantile models under conformal prediction | Calibration is measured, not assumed: the nominal 90% interval covers ~90% out of sample. Exchangeability is the critical assumption |
| [R2.1b](price-forecaster.md) | 2026-07-01 | Price forecaster | drift attribution: regime shift, staleness, or miscalibration | Amended 2026-07-03: the monitor computed coverage and then ignored it, leaving the forecaster's actual product unmonitored. Miscalibration became a third state |
| [R2.2](scenario-generation.md) | 2026-07-08 | Scenario generation | residual-path bootstrap plus Kantorovich reduction | Resampling whole day-vectors preserves intra-day error correlation, which per-hour draws destroy. ~300 paths reduce to ~50 within tolerance |
| [R2.3](stochastic-dispatch.md) | 2026-07-09 | Stochastic dispatch | two-stage CVaR program with intraday recourse | The VSS-collapse trap is real and was escaped deliberately: a linear objective over a price-independent feasible set gives VSS = 0. Budget-limited recourse plus a risk term breaks both conditions, and VSS > 0 is measured out of sample |
| [R2.4](explainability.md) | 2026-07-16 | Dispatch explainability | the SoC dual as a water value, with a no-trade band | The band's width comes from round-trip loss and wear, not from the price. A gate defect was found on 2026-07-26: the dual belongs to the *chosen* optimum, so invariance claims hold only where the dispatch is also invariant |
| [R2.5](value-evaluation.md) | 2026-07-20 | study | VSS as a per-window distribution; a forecast-value baseline in euros | VSS median +12.90 EUR, positive on 66% of 94 real windows. Forecast value is a **null**: statistical skill did not convert into dispatch euros |
| [R2.1c](price-forecaster.md) | 2026-07-24 | Price forecaster | day-ahead load and wind/solar as residual load | Conditioning on the published forecast is leakage-safe and inherits the error a real desk sees. Walk-forward pinball loss falls 13.4% at nominal coverage, re-measured under the rebuilt harness (the 17% first reported came from the harness R2.1d replaced) |
| [R2.2b](scenario-tail.md) | 2026-07-24 | Scenario generation | a peaks-over-threshold tail spliced onto the bootstrap | A bootstrap cannot price a spike beyond its own history. Realized prices above the generator's support ceiling fall from 7.4% to 1.0% |
| [R2.2c](scenario-tail-conditioning.md) | 2026-07-24 | Scenario generation | tail scale conditioned on residual load | Spikes are scarcity events, so they concentrate on tight-margin hours: the fitted scale is ~69% heavier on tight hours than slack ones |
| [R2.5b](tail-dispatch-value.md) | 2026-07-24 | study | tail dispatch value in realized euros | A **null** at every recourse budget. A resolved decision was overturned during implementation: settling at a forecast basis had biased the metric negative by construction. This stopped further tail work |
| [R2.6](bid-curves.md) | 2026-07-26 | study | price-contingent bid curves (an optimizer delta) | Value is a **null**, but the delivery gap is not: the commitment promises 4 to 8 MWh per day on a 2 MWh asset and does not deliver it. Imbalance settlement would price that, and this project does not |
| [R2.1d](forecaster-evaluation.md) | 2026-07-28 | Price forecaster | the walk-forward harness rebuilt | The instrument was wrong, not the forecaster: "3 folds" was one contiguous fortnight, so every prior number was a mid-May statement. The coverage claim survived the rebuild, now on 4.7 years and two zones |
| [R2.1e](target-normalization.md) | 2026-07-28 | Price forecaster | optional de-levelled forecast target | Conditional coverage improves 24% with tighter intervals, and the training-window sweep flips: crisis history is harmful under a raw target and useful under a de-levelled one. An earlier reading called it a null, having measured all three changes as a bundle. Also surfaced a quantile-crossing defect that had passed on one lucky seed |
| (restructure) | 2026-07-28 | (structural) | capability vocabulary, studies split, formulation recut | Changed no number: the diff was verified to preserve every numeric literal and definition body |
| [R2.7](study-windowing.md) | 2026-07-29 | study | the value studies re-measured on 260 days over four years and two markets | **The three nulls hardened and the one positive result shrank.** VSS falls from +12.90 to +3.56 on NL, whose interval now includes zero, while BE holds at +8.36; about 4 EUR of that was a seeding defect where a window's result depended on its position in the series. The unpriced delivery gap was the only quantity the wider window strengthened |
| [R2.8](draw-noise.md) | 2026-07-29 | study | seed reproducibility of the value headlines | Draw noise is worth 4.85 EUR on the VSS median and 11.19 on forecast value, about a third of each study's window interval and covered by no interval reported before. Both published headlines were low draws, so the pages now lead with the mean across seeds. **The draw moves magnitudes, not signs**: every finding keeps its direction under reseeding |

---

## Where the detail lives

This ledger is deliberately one line per phase. Each phase's design detail, its
resolved decision trail, and what it ruled out are in its own spec, under
**Decisions**, which is where a reader should go for the reasoning.

For findings written up for a reader rather than a builder, see
[studies/](../studies/).

## Adding a phase

1. Copy [`_TEMPLATE.md`](_TEMPLATE.md); fill scope, interfaces, and the test contract.
   Add it to **In flight** above, which is where a spec lives until it is green.
2. Human review and approval, before any implementation.
3. Write the golden and property tests first, failing.
4. Implement to green.
5. Move the spec from **In flight** to a ledger row, and update
   [STATE.md](../STATE.md).

Resolve each open question in place, keeping the proposal, so the section becomes
the decision trail rather than a list of questions that were answered elsewhere.
