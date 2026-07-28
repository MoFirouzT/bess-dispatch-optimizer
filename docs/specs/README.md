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
later. Reader-facing documents name capabilities instead; the IDs survive here, in
git history, and in ADR bodies, where chronology is the point.

| Capability | Phases | Packages |
| --- | --- | --- |
| Dispatch core | R1.1, R1.2, R1.3 | `bess.assets`, `bess.validation`, `bess.optimizer` |
| Data feed | R1.4b, R1.4c | `bess.data` |
| Backtest | R1.4a | `bess.backtest` |
| Serving | R1.5 | `bess.api` |
| Price forecaster | R2.1, R2.1b, R2.1c, R2.1d, R2.1e | `bess.forecaster` |
| Scenario generation | R2.2, R2.2b, R2.2c | `bess.scenarios` |
| Stochastic dispatch | R2.3 | `bess.stochastic`, `bess.recourse` |
| Dispatch explainability | R2.4 | `bess.explain` |
| (studies, not a capability) | R2.5, R2.5b, R2.6 | `bess.studies` |

---

## The ledger

One row per phase, oldest first. Dates are the implementing commit's date. The
**finding** column is the point: what the phase established, including when the
answer was "no".

| Phase | Date | Capability | What changed | Finding |
| --- | --- | --- | --- | --- |
| [R1.1](R1.1-deterministic-core.md) | 2026-06-24 | Dispatch core | the deterministic MILP: physics, mutual exclusion, terminal SoC | Grid-side metering locked as the correctness trap: efficiency lives in the SoC balance and never in the objective |
| [R1.2](R1.2-degradation.md) | 2026-06-25 | Dispatch core | wear as a cost subtracted from the objective | Regrounded on 2026-07-13: the original convex-PWL cost was self-derived and matched no source, replaced by the published linear DoD-stress case, which is also step-size invariant |
| [R1.3](R1.3-validation.md) | 2026-06-26 | Dispatch core | closed-form feasibility test ahead of the solver | Adds no math: the conditions are algebraic corollaries of R1.1. Ramp-free reachability is necessary and sufficient; with ramp it stays a sound filter only |
| [R1.4a](R1.4a-backtest.md) | 2026-06-26 | Backtest | three revenue quantities and a leakage boundary | The ordering is provable, so it gates. On real NL a no-look-ahead rolling policy captures ~99% of the perfect-foresight ceiling: the deterministic problem is essentially solved, and the value left is uncertainty |
| [R1.4b](R1.4b-entsoe-loader.md) | 2026-06-26 | Data feed | live ENTSO-E day-ahead loader (BE/NL) | Schema fetched and inspected before coding against it. The parquet cache built here went unused until 2026-07-26, when it was switched on |
| [R1.5](R1.5-serving.md) | 2026-06-26 | Serving | FastAPI dispatch service with a solver circuit breaker | Availability is the contract: a solver timeout serves the greedy schedule rather than failing the request |
| [R1.4c](R1.4c-ingestion-guard.md) | 2026-07-01 | Data feed | a second circuit breaker, on the data feed | A stale price is more dangerous than an obvious outage, because it fails silently. The stuck-feed check keys on a repeated *arbitrary* value, not a focal one: the market really does clear at exactly €0.00 for hours on end |
| [R2.1](R2.1-forecaster.md) | 2026-07-01 | Price forecaster | LightGBM quantile models under conformal prediction | Calibration is measured, not assumed: the nominal 90% interval covers ~90% out of sample. Exchangeability is the load-bearing assumption |
| [R2.1b](R2.1b-drift-monitor.md) | 2026-07-01 | Price forecaster | drift attribution: regime shift, staleness, or miscalibration | Amended 2026-07-03: the monitor computed coverage and then ignored it, leaving the forecaster's actual product unmonitored. Miscalibration became a third state |
| [R2.2](R2.2-scenarios.md) | 2026-07-08 | Scenario generation | residual-path bootstrap plus Kantorovich reduction | Resampling whole day-vectors preserves intra-day error correlation, which per-hour draws destroy. ~300 paths reduce to ~50 within tolerance |
| [R2.3](R2.3-stochastic-recourse.md) | 2026-07-09 | Stochastic dispatch | two-stage CVaR program with intraday recourse | The VSS-collapse trap is real and was escaped deliberately: a linear objective over a price-independent feasible set gives VSS = 0. Budget-limited recourse plus a risk term breaks both conditions, and VSS > 0 is measured out of sample |
| [R2.4](R2.4-explainability.md) | 2026-07-16 | Dispatch explainability | the SoC dual as a water value, with a no-trade band | The band's width comes from round-trip loss and wear, not from the price. A gate defect was found on 2026-07-26: the dual belongs to the *chosen* optimum, so invariance claims hold only where the dispatch is also invariant |
| [R2.5](R2.5-value-evaluation.md) | 2026-07-20 | study | VSS as a per-window distribution; a forecast-value baseline in euros | VSS median +12 EUR, positive on 62% of 63 real windows. Forecast value is a **null**: statistical skill did not convert into dispatch euros |
| [R2.1c](R2.1c-exogenous-fundamentals.md) | 2026-07-24 | Price forecaster | day-ahead load and wind/solar as residual load | Conditioning on the published forecast is leakage-safe and inherits the error a real desk sees. Walk-forward pinball loss falls ~17% at nominal coverage |
| [R2.2b](R2.2b-spike-tail.md) | 2026-07-24 | Scenario generation | a peaks-over-threshold tail spliced onto the bootstrap | A bootstrap cannot price a spike beyond its own history. Realized prices above the generator's support ceiling fall from 7.4% to 1.0% |
| [R2.2c](R2.2c-conditional-tail.md) | 2026-07-24 | Scenario generation | tail scale conditioned on residual load | Spikes are scarcity events, so they concentrate on tight-margin hours: the fitted scale is ~69% heavier on tight hours than slack ones |
| [R2.5b](R2.5b-tail-dispatch-value.md) | 2026-07-24 | study | tail dispatch value in realized euros | A **null** at every recourse budget. A resolved decision was overturned during implementation: settling at a forecast basis had biased the metric negative by construction. This stopped further tail work |
| [R2.6](R2.6-bid-curves.md) | 2026-07-26 | study | price-contingent bid curves (an optimizer delta) | Value is a **null**, but the delivery gap is not: the commitment promises 4 to 8 MWh per day on a 2 MWh asset and does not deliver it. Imbalance settlement would price that, and this project does not |
| [R2.1d](R2.1d-evaluation-honesty.md) | 2026-07-28 | Price forecaster | the walk-forward harness rebuilt | The instrument was wrong, not the forecaster: "3 folds" was one contiguous fortnight, so every prior number was a mid-May statement. The coverage claim survived the rebuild, now on 4.7 years and two zones |
| [R2.1e](R2.1e-target-normalization.md) | 2026-07-28 | Price forecaster | optional de-levelled forecast target | A **null** at the shipped window, but it flips the training-window sweep: crisis history is harmful under a raw target and useful under a de-levelled one. Also surfaced a quantile-crossing defect that had passed on one lucky seed |
| [S1](S1-capability-restructure.md) | 2026-07-28 | (structural) | capability vocabulary, studies split, formulation recut | Changed no number: the diff was verified to preserve every numeric literal and definition body |

---

## Where the detail lives

This ledger is deliberately one line per phase. Each phase's design detail, its
resolved decision trail, and what it ruled out are in its own spec, under
**Open questions**, which is where a reader should go for the reasoning.

For findings written up for a reader rather than a builder, see
[studies/](../studies/).

## Adding a phase

1. Copy [`_TEMPLATE.md`](_TEMPLATE.md); fill scope, interfaces, and the test contract.
2. Human review and approval, before any implementation.
3. Write the golden and property tests first, failing.
4. Implement to green.
5. Add a ledger row here, and update [STATE.md](../STATE.md).

Resolve each open question in place, keeping the proposal, so the section becomes
the decision trail rather than a list of questions that were answered elsewhere.
