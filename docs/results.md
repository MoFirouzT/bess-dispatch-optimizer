# Results

What the stack was measured to be worth: the deterministic ceiling, the value of the
uncertainty layer, the four questions that came back null, the dual that explains a
schedule, and the scope this project does not cover.

*Assumes:*
the capability map in [architecture.md](architecture.md);
the evaluation semantics in [formulation-evaluation.md](formulation-evaluation.md);
each number's method is named in the [study](studies/) it comes from.

---

## The deterministic ceiling

Two results anchor the project:
the deterministic core is close to tight, so the value that remains is in handling price *uncertainty*, and that value is measurable and positive.

**On real Dutch day-ahead prices, a rolling, no-look-ahead policy captures 99.0% of the perfect-foresight revenue ceiling.**
Once the price curve is known, a myopic per-day policy is already near-optimal, so the deterministic problem is essentially solved.
The 1.0% left on the table is overnight foresight.
Not knowing prices in advance is the separate and larger problem, and it is what Release 2 targets;
its result is a **measured value of the stochastic solution (VSS) with a positive median across real out-of-sample days** (see [Value under uncertainty](#value-under-uncertainty)).

The [baseline table in the README](../README.md#results) reports the three revenues: a worked example over a 91-day 2024-Q2 ENTSO-E NL day-ahead window (1 MWh / 1 MW asset, η = 0.95), **net of a priced linear degradation cost** (€15/MWh of throughput).
No price data is committed; set an ENTSO-E token and run [`examples/worked_example.py`](../examples/worked_example.py) to reproduce, without a token it falls back to a synthetic series.

Rolling is each day's independent optimum (solved empty-to-empty with full knowledge of that day only), so the whole €84 gap to the ceiling (1.0%) is pure cross-day carry:
overnight SoC a per-day agent cannot justify without tomorrow's prices.
Wear is priced, not ignored:
it removes nearly a third of gross ceiling revenue (€11,643 gross → €8,139 net) and cuts the degradation-blind greedy floor harder.
Annualized, this volatile quarter puts the net ceiling near €33k per MWh-installed per year; a calmer year sits lower.

Storage duration (energy-to-power ratio) is a reported axis, not a fixed choice:
a longer asset arbitrages a flatter slice of the daily spread, so on the same real quarter the annualized ceiling falls from ~€33k/MWh·yr at 1 h to ~€24k at 4 h ([the duration study](studies/storage-duration.md);
run [`examples/duration_sweep.py`](../examples/duration_sweep.py) for the {1h, 2h, 4h} sweep).

![Optimal dispatch on the widest-spread real day (2024-05-01): the battery charges through the cheap overnight hours and a deeply negative-priced midday, then discharges into the morning and evening price peaks, returning to empty by end of day.](figures/example-dispatch-day.svg)

## Value under uncertainty

The deterministic result above assumes the price curve is known.
Release 2 drops that assumption:
it forecasts prices as calibrated intervals, samples them into scenarios, and solves a two-stage risk-aware program that commits a day-ahead schedule now and re-dispatches intraday once prices realize.

The forecaster predicts each price as a *calibrated interval*, not a point:
LightGBM quantile models wrapped in conformal prediction.
Calibration is measured rather than assumed.
On real NL prices, the nominal 90% interval covers the realized price **89.2% of the time** out-of-sample under a leakage-safe walk-forward, so the scenarios drawn from it inherit an honest spread instead of false confidence.
Calibration alone is cheap (a wide interval covers everything), so accuracy is measured separately:
at the interval edges the forecaster's pinball loss is **0.22x / 0.28x a seasonal-naive baseline's** under the same walk-forward (below 1 is skill).

![Conformal price forecast on a held-out block: the shaded 90% interval, the point forecast, and the realized price; the interval widens where the price is volatile (heteroscedastic) and the realized price lands inside it close to the nominal 90% of the time.](figures/example-forecast-intervals.svg)

Reproduce with `uv run --group forecast --group examples python examples/forecast_demo.py` (token, synthetic fallback otherwise).

That forecaster began as an autoregression:
its features were lagged prices (24 to 168 hours back, all old enough to be known before the auction closes) plus hour-of-day, day-of-week, and holiday flags.
But a day-ahead price is the clearing point of an auction, and where it lands on the supply stack is set by **residual load**, the demand left after non-dispatchable wind and solar.
The forecaster adds that driver:
ENTSO-E publishes day-ahead load and wind/solar forecasts before the auction closes, so conditioning on residual load is both leakage-safe (it is the published forecast for the target hour, never the realized value) and honest (it inherits the same forecast error a real desk sees).
Feeding it cuts the forecaster's walk-forward pinball loss by **13.4%** on real NL while empirical coverage stays at the nominal 90%, so the scenarios drawn downstream start from a sharper, better-conditioned signal.

A forecaster deployed against a live market decays, so the drift monitor watches its trailing accuracy and attributes *why* it degraded:
a **regime shift** (the market moved; even a naive baseline degrades, so wait), **staleness** (the model fell behind a seasonal-naive, so retrain), or **miscalibration** (the intervals stopped covering, so recalibrate):
an actionable alarm rather than a bare "accuracy dropped."

![Drift attribution map: the monitor's decision regions over the error ratio (forecaster vs. seasonal-naive MAE) and the input shift (PSI), each region coloured by what the real classifier returns there. Staleness (retrain) owns the whole high-ratio half regardless of input shift; regime shift (wait) is the high-PSI, low-ratio corner; miscalibration sits inside the healthy region because coverage is a third axis this map cannot show.](figures/example-drift-regions.svg)

Reproduce with `uv run --group examples python examples/drift_demo.py` (synthetic by design: it renders the classifier's decision regions, not a market result).

Two later studies pushed on the intervals themselves and neither changed a shipped default.
A 324-configuration [search for a narrower interval](studies/interval-sharpness.md) found one on NL, 4.5% tighter, and the per-hour calibration check rejected it: the narrowing fixes over-coverage at 21:00 and pushes 11:00 below the band.
Conformal coverage does decay across a regime shift (0.897 in 2024 against 0.791 across the 2021 crisis ramp), so the two published repairs for it, weighted conformal and adaptive conformal inference, were built and measured; [both came back null](studies/drift-robust-conformal.md) at a monthly refit, adding at most +0.019 worst-year coverage.
What that run did find is that the decay is mostly the *model* going stale rather than the calibration: refitting monthly rather than annually is worth +0.18 coverage on the crisis year and a 35% narrower interval.

A residual-path bootstrap then generates a few hundred price paths, and forward-selection reduction keeps the ~50 that best preserve the distribution (measured by Kantorovich distance), so the stochastic program stays small without discarding the tails that risk-aware dispatch cares about.

![Scenario reduction: Kantorovich distance to the full set vs. the number of paths kept (forward selection beats the k-means baseline), and the wall-clock cost of reducing, which together justify keeping ~50 of ~300.](figures/example-scenario-reduction.svg)

For a battery the decision-relevant part of the price distribution is its **tail**: a scarcity spike is precisely the hour to have saved charge for. Two refinements make that tail faithful. The residual-path bootstrap can only replay forecast errors it has already seen, so the largest spike any scenario prices is capped at the historical maximum, and real markets spike past it. Scenario generation fits an **extreme-value tail**, a Generalized Pareto distribution over the residual exceedances above a high threshold, and splices it onto the bootstrap, so a scenario can price an unprecedented spike in a calibrated way rather than by an arbitrary multiplier. On real NL held-out days, the share of realized prices above the plain generator's support ceiling (the highest price it gives any probability at all) falls from **7.4% to 1.0%**: spikes the capped bootstrap ruled out are now represented.

![Scenario tail: a histogram of forecast residuals with the fitted Generalized Pareto tail drawn over the high-threshold exceedances, beside the highest price each generator can produce; the plain bootstrap is capped at the historical-maximum residual while the extreme-value tail extends well beyond it.](figures/example-spike-tail.svg)

A spike is a scarcity event, so it does not fall uniformly across the day: it concentrates on tight-margin hours, high load against low renewables. A second refinement ties the tail's scale to residual load, the same driver the forecaster conditions on, so the tail is heavier in the hours where spikes actually happen. The dependence is measured, not assumed: on real NL the fitted tail scale rises about **69%** from slack hours to tight hours, so the risk-aware program reserves stored energy for the hours that actually risk a spike.

![Conditional scenario tail: historical spike sizes (excess over the threshold) plotted against residual load, with the fitted conditional Generalized Pareto scale rising over the flat unconditional one; spikes are systematically larger on high-residual-load (tight-margin) hours, which the unconditional tail spreads uniformly.](figures/example-conditional-tail.svg)

Reproduce the two tail figures with `uv run --group examples python examples/spike_tail_demo.py` and `examples/conditional_tail_demo.py` (both synthetic by design: they demonstrate the tail mechanism, not a market result).

That machinery only earns its place if it beats simply optimizing against the mean forecast. Repeating the out-of-sample measurement over **260 real delivery days spread across 2022 to 2025** (commitments fit on the trailing 28 days, then scored, fixed, on that day's realized prices) gives a **median per-window VSS of +8.36 EUR on BE**, whose 95% window interval [+4.57, +13.27] sits above zero, and **+5.76 EUR on NL**, whose interval does not. Both are for the 2 MWh / 1 MW study asset.

Each of those numbers carries two independent widths, both measured: the window interval above, and the spread from the random scenario draw itself (4.85 EUR here, so the NL headline is a mean over ten seeds rather than a single draw). Reseeding moves the magnitude and not the sign.

So the stochastic layer pays, the effect is **regime-dependent** (the 2022 gas crisis pays several times what calm years do), and on Dutch prices alone it is not separable from zero. An earlier version of this section claimed +12.90 EUR on one 2024 quarter; [re-measuring on a four-year span](specs/study-windowing.md) is what moved it, and the studies pages record the decomposition.

![Per-window out-of-sample VSS across the evaluation span: a histogram of windows straddling zero with its median above it; the stochastic commitment usually, but not always, beats the mean-value plan out-of-sample.](figures/example-vss-distribution.svg)

Reproduce with `uv run --group examples python examples/vss_study.py --mode full` (token, synthetic fallback otherwise; drop the flag for a fast strided preview). The mechanism, the risk/return frontier, and the full per-window distribution are in [docs/studies/stochastic-value.md](studies/stochastic-value.md).

## What was measured, and what came back null

The stochastic *structure* earns money. Three attempts to earn more by feeding it a better picture of tomorrow did not, and they are reported as nulls rather than quietly dropped:

| Question | Answer |
| --- | --- |
| Does a better price forecast earn more euros than a seasonal-naive one? | [**Null**](studies/forecast-value.md) in both markets, despite clear statistical skill |
| Does pricing unprecedented spikes in the scenarios earn more? | [**Null**](studies/tail-value.md) at every recourse budget and in every year |
| Does a price-contingent bid curve beat a single blind schedule? | [**Null**](studies/bid-curves.md) on euros, but it surfaced an unpriced delivery gap of 4 to 8 MWh per day on a 2 MWh asset |

All three share one mechanism: **intraday recourse adjusts after the price is known**, so a sharper day-ahead forecast has little left to improve. Each was separated from a broken comparison by a designed instance where the effect *is* detected, and each carries golden and property gates on its scoring arithmetic.

Re-measuring all four on the wider span moved every one in the same direction: **the three nulls hardened and the one positive result shrank.** The delivery gap was the only quantity the wider window strengthened, which is why imbalance settlement is the next thing worth building. The full set, including how the nulls were validated, is in **[docs/studies/](studies/)**.

Solve time grows manageably on both axes ([details](studies/solve-scaling.md)): the deterministic MILP grows with the horizon, from ~9 ms for a day to ~120 ms for a month, while the two-stage program grows with the scenario count, from ~0.5 s at 10 scenarios to ~2.0 s at 50. That second axis is exactly the cost the reduction step (~300 → ~50 paths) keeps bounded.

The plotting dependency is optional: `uv sync --group examples` installs it.

## Why the battery holds

A schedule says *what* the battery does; the dual of the state-of-charge balance says *why*. That shadow price is the **water value**: the marginal worth of a stored MWh, borrowed from hydro-reservoir scheduling. It is flat while the battery is neither full nor empty and steps at a SoC bound, and it defines a **no-trade band** on price: charge only below the band, discharge only above it, hold in between. The band's width comes from round-trip loss and wear, not from the price, so an idle hour at a high price is explained rather than asserted, and each executed trade reports its breakeven slippage. `POST /explain` returns the schedule and this explanation from a single solve; the details are in [formulation.md §R2.4](formulation.md#r24-shadow-price-explainability-derived-no-optimizer-change) and [the MILP dual re-solve rule](decisions/milp-dual-resolve-rule.md).

![Water value and no-trade band over a day: the shadow price of stored energy (flat within a run, stepping at SoC bounds) and the shaded price band it induces; at the €175 hour the price sits inside the band, so the battery idles and holds its charge for the later €200 peak.](figures/example-water-value.svg)

Reproduce with `uv run --group examples python examples/explain_demo.py` (synthetic by design: it demonstrates the dual mechanism, not a market result).


---

## Data reliability

A dispatch is only as trustworthy as the price it was computed from, so the data feed gets its own circuit breaker, distinct from the solver breaker above. `bess.data.ingestion_guard` classifies every fetch as **healthy**, **outage** (no data), or **anomalous-but-present** (a frozen feed, a grid gap, a duplicate timestamp, an out-of-band value), and on either failure falls back to the last-known-good series, reporting the schedule as degraded rather than silently optimal; a stale-but-present price is treated as *more* dangerous than an obvious outage because it fails silently.

The checks key on feed *pathology*, never price *level*: zero and negative prices are legitimate in BE/NL, and the market really does clear at exactly €0.00 for hours on end (8 straight hours on 2024-03-24), so the stuck-feed check fires on a repeated *arbitrary* value, not a repeated focal one. The full classification rules are in [the ingestion-guard spec](specs/data-feed.md).

![Ingestion guard: a feed frozen at an arbitrary price is rejected, and the dispatch runs on the trustworthy last-known-good series instead, so the overall provenance is reported as degraded rather than a silent optimal.](figures/example-ingestion-guard.svg)

Reproduce with `uv run --group examples python examples/ingestion_guard_demo.py`.


---

## Scope and known limitations

The core is a deterministic, single-asset, day-ahead dispatch engine, and its scope boundaries are deliberate:

- **The deterministic core takes prices as known.** The core MILP solves against a given day-ahead curve. Price *uncertainty* is handled by the uncertainty stack layered on top (forecaster → scenarios → two-stage risk-aware dispatch with intraday recourse), whose value over a mean-forecast plan is the VSS reported above, and whose dispatch decisions are explained by the shadow-price layer.
- **Day-ahead arbitrage only.** Intraday, imbalance, and ancillary-service markets (FCR / aFRR) are out of scope; the asset trades a single energy market.
- **No grid-connection / congestion constraint.** Dispatch is not capped at a connection-point limit. Adding a congestion or curtailment cap is the natural next physical constraint and is relevant to Dutch (TenneT) grid conditions.
- **Linear degradation only.** The degradation cost is linear in throughput (the linear DoD-stress case); the nonlinear convex deep-cycle penalty, rainflow cycle-counting, and calendar aging are not modelled.
- **The asset is a price taker, and that is asserted rather than measured.** Dispatch optimizes against the price and never feeds back into it. The assumption is sound for the 2 MWh / 1 MW study asset, which cannot move a bidding zone that trades in gigawatts, and it is the one claim here that carries no measurement. Modelling the feedback needs an endogenous price (a residual supply curve); a cheaper first step is to re-score an existing schedule under an impact model and see where the price-taking optimum starts over-concentrating.
- **Committed volume can exceed what the battery delivers, and the gap is unpriced.** The [bid-curve study](studies/bid-curves.md) measures it (median 4 to 8 MWh per day on a 2 MWh asset, depending on the recourse budget) but does not charge for it: imbalance settlement is what would, and it is not modelled.
- **Single asset, single node.** No portfolio of assets and no network model.
