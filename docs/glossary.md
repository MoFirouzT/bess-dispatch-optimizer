# Glossary / knowledge bank

*Assumes: familiarity with linear/integer programming. Battery and market terms are defined here from scratch.*

Entry shape: **term:** definition. *Why here:* relevance to this project. *Gotcha:* the common error or subtlety a bug (or a careless reading) trips on. Grown one section per build phase. The gotcha field is what makes this a living artifact rather than a dictionary.

---

## Market

**Day-ahead (DA) market**: auction (EPEX SPOT, gate closure 12:00 CET on D-1) clearing the next day's energy at the marginal price. *Why here:* the price input the optimizer arbitrages. *Gotcha:* since 2025-10-01 it clears in **15-minute** MTU (96 periods/day), not hourly; a model built on "24 periods" is now modelling a published index, not the real product.

**Market Time Unit (MTU)**: the settlement granularity of a market product. *Why here:* sets the optimizer's period length `Δt`. *Gotcha:* DA MTU is now 15-min in BE/NL; the 60-min series is just the average of the four quarter-hours.

**Gate closure**: the deadline after which a market's bids are firm. *Why here:* defines the information set at decision time and the look-ahead-bias boundary in the backtest. *Gotcha:* the whole 24h day-ahead schedule is committed at the 12:00 CET gate. That single-shot commitment is *why* a naive day-ahead stochastic model has no recourse value.

**Imbalance settlement**: real-time charge/payment for deviating from your nominated schedule, per 15-min ISP. *Why here:* distinct from arbitrage; the value proposition must not conflate them. *Gotcha:* a "day-ahead dispatch optimizer" does **not** reduce imbalance costs unless it models the imbalance market; claiming so is a market-mechanics error.

**FBMC (Flow-Based Market Coupling)**: the CORE-region method allocating cross-border capacity in the day-ahead clear. *Why here:* explains why BE and NL prices are tightly correlated. *Gotcha:* BE/NL co-movement means a "BE optimizer" and "NL optimizer" share most of their signal.

**FCR / aFRR / mFRR**: frequency-response reserve products (primary/secondary/tertiary). *Why here:* reference only; out of build scope, but kept for correctness of reasoning about the wider market. *Gotcha:* FCR is **symmetric** (equal up/down) in 4-hour blocks with a 15-min sustain requirement (→ SoC headroom); aFRR is **asymmetric** with separate capacity and activation revenue. Conflating the two is a common modeling error.

**TSO / BRP**: Transmission System Operator (TenneT in NL, Elia in BE) / Balance Responsible Party. *Why here:* the BRP is who bears imbalance; the TSO publishes prices and procures reserves.

**Negative prices**: day-ahead prices below zero during renewable oversupply. *Why here:* increasingly common; the formulation must handle them. *Gotcha:* under negative prices, simultaneous charge+discharge could look "profitable" (burning energy); the mutual-exclusion binary exists to prevent that.

---

## Battery / physical

**State of charge (SoC)**: energy currently stored, in MWh. *Why here:* the coupling state across periods. *Gotcha:* the SoC balance is where efficiency lives; a sign or placement error here is the #1 correctness trap.

**Round-trip efficiency (η_rt = η_ch·η_dis)**: fraction of energy returned over a full charge→discharge cycle. *Why here:* sets the minimum price spread that makes a trade profitable. *Gotcha:* it's **emergent** from the grid-side balance, not a term you multiply into revenue; delivering 1 MWh costs 1/η_rt MWh drawn.

**Inverter / power limit**: max charge or discharge power (MW). *Why here:* a hard physical constraint and a validation check. *Gotcha:* "can't charge faster than the inverter": energy capacity and power capacity are independent (1 MWh / 1 MW = 1-hour battery).

**C-rate**: charge/discharge power relative to capacity (1C = full energy in 1 h). *Why here:* a 1 MWh/1 MW battery is 1C; duration = 1/C-rate.

**Depth of discharge (DoD) / cycle**: how deep a discharge goes / one full charge-discharge. *Why here:* drives degradation. *Gotcha:* deep cycles age the cell faster than shallow ones, which is why degradation is modelled as a non-linear (PWL) cost rather than a flat per-MWh fee.

**Degradation**: capacity/health loss from cycling and calendar age. *Why here:* a cost term in the objective (R1.2). *Gotcha:* if ignored, the optimizer over-cycles for tiny spreads; the PWL cost must make marginal deep cycling unprofitable.

---

## Optimization

**MILP**: Mixed-Integer Linear Program. *Why here:* the dispatch model (binaries for charge/discharge exclusivity; PWL via SOS2). *Gotcha:* the solve time is the solver's, not the modelling language's: a Pyomo-vs-JuMP "speed race" on a small MILP measures construction overhead, i.e. noise.

**LP relaxation**: the MILP with integrality dropped. *Why here:* its tightness governs branch-and-bound speed. *Gotcha:* a loose big-M weakens the relaxation; prefer indicator constraints / SOS, and let the power cap *be* the big-M.

**SOS2 (Special Ordered Set type 2)**: at most two consecutive members non-zero; encodes piecewise-linear functions. *Why here:* the general tool for **non-convex** PWL. R1.2's degradation cost is *convex*, so it uses the simpler **epigraph form** (max of segment lines, pure LP) instead; SOS2 is documented as the non-convex path. *Gotcha:* HiGHS has no native SOS support, so a non-convex PWL would need a SOS-capable solver or a binary segment-selection encoding; for convex PWL, SOS2 is unnecessary anyway.

**Recourse / two-stage stochastic program**: first-stage decisions made under uncertainty, second-stage decisions adapt after it resolves. *Why here:* the R2.3 layer. *Gotcha:* with a linear objective and a price-independent feasible set, the two-stage program **collapses to the mean** (VSS=0); value needs a risk-aware objective or genuine recourse.

**Value of the Stochastic Solution (VSS)**: gain from solving the stochastic model vs. optimizing on the mean forecast. *Why here:* the headline Release-2 metric. *Gotcha:* a measured VSS≈0 means the recourse structure is wrong, not that stochastic methods "don't help."

**Chance constraint / CVaR**: constrain a probability (e.g. P(profit>0)≥0.95) / penalize tail loss. *Why here:* the risk-aware path that adds value even single-shot. *Gotcha:* this is where stochastic value comes from when there's no recourse.

**Shadow price (dual)**: marginal value of relaxing a constraint by one unit. *Why here:* the explainability endpoint (why the battery sat idle during a spike). *Gotcha:* duals are only well-defined for the LP relaxation / fixed integers, so be precise about what you're reporting.

**MPC / receding horizon**: re-optimize on a rolling, shrinking window as new information arrives. *Why here:* the intraday recourse layer *is* this. *Gotcha:* needs a re-optimization trigger and state (SoC) continuity across windows; warm-start each re-solve from the previous one.

**Benders decomposition**: split a large two-stage problem into a master + subproblems. *Why here:* the optional Julia/JuMP scale comparison. *Gotcha:* only worth it at scenario scale, not on the base MILP.

---

## Testing & correctness

**Test oracle**: the mechanism that decides whether a test's output is correct. *Why here:* the whole correctness story rests on having a trustworthy oracle for an optimizer whose "right answer" isn't obvious by inspection. *Gotcha:* the hard part of testing an optimizer is the *oracle problem*, since a plausible-looking schedule can be silently suboptimal, so an independent source of truth (a second solver, a hand-computed case) is what makes the assertion meaningful.

**Golden (oracle) test**: a test asserting the output equals a pinned, known-correct reference value stored with the test. *Why here:* `tests/golden/` gates the formulation; a golden case catches a refactor that silently changes constraint meaning (efficiency misplaced, a sign flipped) while still producing a valid-looking schedule. *Gotcha:* a golden test is only as good as how its reference was derived; regenerating the "golden" value from the current code turns it into a tautology that passes no matter what.

**Property-based test (Hypothesis)**: assert an *invariant* that must hold for all valid inputs, and let the framework generate many inputs trying to break it. *Why here:* `tests/property/` checks structural invariants (SoC stays in `[0, capacity]`, power never exceeds the inverter limit, no simultaneous charge+discharge) that no single golden case could cover. *Gotcha:* on failure Hypothesis *shrinks* to the minimal counterexample, so a reported failure is already the simplest one: don't dismiss it as an exotic edge case.

---

## ML / validation

**Conformal prediction**: wraps any model to produce intervals with distribution-free coverage. *Why here:* the forecaster outputs price *intervals*, not points (via MAPIE). *Gotcha:* coverage holds under exchangeability; recalibrate on a rolling window as the price distribution drifts.

**Split conformal vs. CQR**: two conformal constructions: split conformal adds a constant-width band around a point model; conformalized quantile regression (CQR) conformalizes lower/upper quantile models for *input-adaptive* width. *Why here:* R2.1 defaults to CQR ([ADR-0014](decisions/0014-cqr-over-split-conformal.md)) because day-ahead prices are heteroscedastic. *Gotcha:* both guarantee only *marginal* coverage, never conditional; MAPIE 1.x CQR needs three prefit quantile models, not one.

**Prediction interval**: a range `[lower, upper]` expected to contain the realized value at a nominal rate. *Why here:* the forecaster's output and the input the R2 stochastic layer samples. *Gotcha:* an interval is honest only if *empirical* coverage matches nominal out-of-sample; a 90% interval covering 99% is as miscalibrated as one covering 70%.

**Coverage**: fraction of true values falling inside the predicted interval. *Why here:* the forecaster's acceptance gate. *Gotcha:* nominal 90% must be *empirically* ~90% out-of-sample, or the intervals are miscalibrated.

**Walk-forward (expanding window) validation**: train on the past, test on the strictly-later future, roll forward. *Why here:* the only valid backtest scheme for time series. *Gotcha:* a random train/test split leaks the future; transfers directly from financial-ML discipline.

**Look-ahead / leakage**: using information not available at decision time. *Why here:* the backtest's leakage assertion guards it. *Gotcha:* if the backtest beats perfect foresight, it's leakage, not alpha; hence the sanity band.

**Perfect-foresight baseline**: the optimum given the realized prices. *Why here:* the ceiling; results are reported as "% of perfect foresight captured." *Gotcha:* it's an upper bound by construction: nothing can exceed it.

---

## Data reliability & MLOps

**Ingestion circuit breaker**: a breaker wrapping the data *fetch* (as opposed to the solver breaker wrapping the *solve*), classifying each fetch and falling back to last-known-good on failure. *Why here:* R1.5b (`bess.data.ingestion_guard`); a wrong dispatch from silently-bad input data is as real a failure as a wrong formulation. *Gotcha:* it must stay a *separate* breaker from the solver one; a shared breaker firing on data corruption looks identical in the logs to a slow solver (ADR-0012).

**Outage vs. anomalous-but-present**: the two data-failure classes: an outage is *no present data* (timeout, 5xx); an anomaly is *present but untrustworthy data* (stuck feed, gap, duplicate, out-of-band). *Why here:* the guard's core taxonomy. *Gotcha:* the anomaly is the *more* dangerous case, since a stale-but-present price flows silently into a live dispatch whereas an outage is obvious.

**Stuck / frozen feed**: a feed repeating a bit-identical value long past when a real market would have moved. *Why here:* the guard's headline anomaly check. *Gotcha:* key on the *repetition*, not the value; zero and negative prices are legitimate in BE/NL, so flagging "€0.00" would misread a real solar-glut day as corruption.

**EPEX SDAC price limits**: the harmonised clearing-price bounds of the single day-ahead coupling: min −600 €/MWh (from 2026-05-28), max 4000 €/MWh, escalatable in +1000 steps. *Why here:* the guard's out-of-band check is grounded in these, not a guessed range. *Gotcha:* it's a *market technical bound*, not the year-specific revenue sanity band; a value outside it cannot be a real clearing price.

**Provenance composition**: combining the ingestion status and the solver mode into one overall trust label. *Why here:* R1.5b / ADR-0013; a solve that is optimal on stale fallback data is reported *degraded*, not healthy. *Gotcha:* if a consumer reads `mode="optimal"` alone it re-opens the silent-stale-dispatch hole; the composition exists to prevent that.

**Population Stability Index (PSI)**: a binned divergence measure between a reference and a current distribution, used to flag input drift. *Why here:* the R2.1b drift monitor's regime-shift signal (`psi ≥ 0.2` ⇒ inputs moved materially). *Gotcha:* PSI tells you *that* a distribution moved, not *why*; the skill is separating a genuine regime shift from model staleness.

**Regime shift vs. model staleness**: two causes of rising forecast error: the market genuinely changed (a naive baseline degrades too) vs. this model decayed (its error creeps up while a naive baseline's does not). *Why here:* R2.1b classifies them rather than emitting an undifferentiated "drift detected", staleness-first ([ADR-0015](decisions/0015-drift-staleness-before-regime.md)). *Gotcha:* conflating them is the realistic failure; retraining fixes staleness but not a regime shift.

**Interval miscalibration (coverage drift)**: a third drift state: the point forecast still tracks and inputs are stable, but the conformal *intervals* under-cover (empirical coverage falls materially below nominal). *Why here:* the forecaster's product is calibrated intervals, and R2.2 samples scenarios from them, so a silent coverage collapse is its own failure mode ([ADR-0016](decisions/0016-drift-coverage-as-distinct-state.md)), checked after regime and mapped to *recalibrate*, not retrain. *Gotcha:* coverage over a short window is noisy, so the flag is one-sided (under-coverage only) and guarded by a minimum sample count.
