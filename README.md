# bess-dispatch-optimizer

[![CI](https://github.com/MoFirouzT/bess-dispatch-optimizer/actions/workflows/ci.yml/badge.svg)](https://github.com/MoFirouzT/bess-dispatch-optimizer/actions/workflows/ci.yml)
[![tests](https://img.shields.io/badge/tests-196_(180_CI_%2B_16_live)-brightgreen.svg)](tests/)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Grid-scale batteries earn money by charging when power is cheap and discharging when it is dear, but every cycle ages the cell and volatile renewable-driven prices make the timing hard.
This project computes the revenue-maximizing charge/discharge schedule for that trade-off, for a grid-scale **battery energy storage system (BESS)** in the Belgian/Dutch day-ahead market.

It starts from a deterministic mixed-integer linear program (MILP) that maximizes arbitrage revenue net of cell degradation given a price curve and a battery's physical limits, then builds up to probabilistic price forecasting and a risk-aware stochastic dispatch layer for when prices are *not* known in advance.
Correctness is gated by golden oracles and Hypothesis property tests; the layered architecture, docs charter, and forecast calibration are all enforced in CI.

## What problem this solves

A battery earns money by **buying low and selling high**, but every cycle ages the cell, charging and discharging each lose energy (round-trip efficiency < 1), and the schedule must respect power, energy, and ramp limits.

There are really two problems here.
When the price curve is **known**, dispatch is a deterministic optimization: the project solves it to optimality and measures how much of that ceiling a realistic no-look-ahead policy captures (Release 1).
When prices are **uncertain**, the decision has to hedge across scenarios: the project forecasts prices as calibrated intervals and solves a two-stage risk-aware program whose value over a naive mean-forecast plan is measurable (Release 2).

## The model

The core is a MILP over $T$ dispatch periods that maximizes grid-side arbitrage revenue minus a degradation cost $D_t$:

$$\max \sum_{t} \Bigl[ \pi_t \Delta t (p^{dis}_t - p^{ch}_t) - D_t \Bigr]$$

subject to the state-of-charge balance, the one equation where round-trip efficiency enters:

$$e_t = e_{t-1} + \eta^{ch} p^{ch}_t \Delta t - \tfrac{p^{dis}_t}{\eta^{dis}} \Delta t$$

plus power, energy, and ramp limits, a binary that forbids simultaneous charge and discharge, and a terminal-SoC target. The degradation cost $D_t = c^{deg} \tau_t$ is linear in per-period storage-side throughput (the linear DoD-stress case of the Xu 2018 / Shi 2017 cycle-based model), so it stays native to the LP. Release 2 extends this into a two-stage stochastic program with a CVaR risk term and intraday recourse (§R2.3).

The one non-obvious design choice is that **all power is metered grid-side**, so degradation is a cost subtracted from cash rather than an efficiency factor, and never touches the SoC balance.
The complete model, every constraint, and the governing references are in [docs/formulation.md](docs/formulation.md) (start with its "Model at a glance" summary).

## Status

**Deterministic core and serving (Release 1), complete**, gated by golden + property tests:

- **R1.1**: deterministic MILP dispatch core
- **R1.2**: linear degradation cost on throughput
- **R1.3**: pre-flight feasibility checks
- **R1.4** (backtest, data, and data reliability):
  - **R1.4a**: walk-forward backtest with greedy / rolling / perfect-foresight baselines
  - **R1.4b**: live ENTSO-E day-ahead loader (BE/NL)
  - **R1.4c**: anomaly-aware ingestion guard, a *second* circuit breaker on the data feed, classifying each fetch outage / anomalous-but-present / healthy before it can reach the solver
- **R1.5**: FastAPI dispatch service with a graceful-degradation circuit breaker (greedy fallback on solver timeout), Dockerized

**Release 2 (forecasting → stochastic optimization), complete**, gated by golden + property tests:

- **R2.1**: probabilistic price forecaster: LightGBM quantile models wrapped in conformal prediction (MAPIE) for calibrated day-ahead price *intervals*; on real NL prices the nominal 90% interval achieves **~89% empirical coverage** under a leakage-safe walk-forward (see [Value under uncertainty](#value-under-uncertainty-release-2))
- **R2.1b**: rolling drift monitor: attributes a degrading forecast to a *regime shift* (market moved; a naive baseline degrades too), *model staleness* (decayed relative to a seasonal-naive), or *miscalibration* (intervals under-cover), so the flag is actionable (wait / retrain / recalibrate)
- **R2.2**: scenario generation and reduction: residual-path bootstrap into probability-weighted price paths, reduced ~300 → ~50 within a Kantorovich tolerance
- **R2.3**: risk-aware two-stage dispatch with intraday MPC recourse: a CVaR mean-risk MILP with a measured **value of the stochastic solution (VSS) > 0** out-of-sample, plus a risk/return frontier (see [Value under uncertainty](#value-under-uncertainty-release-2))
- **R2.4**: dual-based explainability: the state-of-charge shadow price as a **water value**, with a no-trade band and per-trade breakeven that say *why* the battery holds rather than trades (see [Why it holds](#why-it-holds-release-2))
- **R2.5**: value evaluation hardening: the VSS re-measured as a **per-window distribution** over real NL days (median positive, ~62% of windows), a **forecast-value baseline** in euros whose per-window distribution comes out centred on zero (a null reported as a null), and **pinball skill** reported beside coverage (see [Value under uncertainty](#value-under-uncertainty-release-2))

## Example results

Two results anchor the project: the deterministic core is essentially tight, so the value that remains is in handling price *uncertainty*, and that value is measurable and positive.

**On real Dutch day-ahead prices, a rolling, no-look-ahead policy captures 99.0% of the perfect-foresight revenue ceiling.**
Once the price curve is known, a myopic per-day policy is already near-optimal, so the deterministic problem is essentially solved. That is the foundation, not the headline: the value left on the table is not overnight foresight but *not knowing prices in advance*, which is exactly what Release 2 targets. That is where the project's differentiated result lives, a **measured value of the stochastic solution (VSS) with a positive median across real out-of-sample days** (see [Value under uncertainty](#value-under-uncertainty-release-2)).

The numbers below are from a worked example over a 91-day 2024-Q2 ENTSO-E NL day-ahead window (1 MWh / 1 MW asset, η = 0.95), **net of a priced linear degradation cost** (R1.2, €15/MWh of throughput). No price data is committed; set an ENTSO-E token and run [`examples/worked_example.py`](examples/worked_example.py) to reproduce (without a token it falls back to a synthetic series):

| Baseline | Net profit (91 days) | Share of ceiling |
| --- | --- | --- |
| Greedy floor (percentile rule) | €4,441 | 55% |
| Rolling deployable (per-day optimal) | €8,056 | **99.0%** |
| Perfect-foresight ceiling | €8,139 | 100% |

Rolling is each day's independent optimum: every day is solved empty-to-empty with full knowledge of *that* day. So the whole €84 gap to the ceiling (1.0%) is pure cross-day carry, the overnight SoC a per-day agent cannot justify without tomorrow's prices, which is exactly what Release 2 targets.

Wear is priced, not ignored. It removes nearly a third of gross ceiling revenue (€11,643 gross → €8,139 net), and cuts the naive greedy floor more, since greedy cycles without regard to degradation.

Annualizing this volatile quarter (~9% negative-price hours) puts the net ceiling near €33k per MWh-installed per year; a calmer year sits lower. Gate D derives its band from each window's own price spread, so a volatile quarter legitimately lands high without tripping it.

These figures are for a **1-hour** asset (1 MWh / 1 MW). Storage duration (energy-to-power ratio) is a reported axis, not a fixed choice: both the capture ratio and the per-MWh value fall as duration grows, because a longer asset arbitrages a flatter slice of the daily spread and leaves more cross-day carry on the table. On the same real quarter, the annualized ceiling drops from ~€33k/MWh·yr at 1h to ~€24k at 4h. Run [`examples/duration_sweep.py`](examples/duration_sweep.py) for the {1h, 2h, 4h} sweep ([ADR-0022](docs/decisions/0022-storage-duration-reported-axis.md)).

![Optimal dispatch on the widest-spread real day (2024-05-01): the battery charges through the cheap overnight hours and a deeply negative-priced midday, then discharges into the morning and evening price peaks, returning to empty by end of day.](docs/figures/example-dispatch-day.svg)

### Value under uncertainty (Release 2)

The deterministic result above assumes the price curve is known. Release 2 drops that assumption: it forecasts prices as calibrated intervals (R2.1), samples them into scenarios (R2.2), and solves a two-stage risk-aware program that commits a day-ahead schedule now and re-dispatches intraday once prices realize (R2.3).

The forecaster (R2.1) predicts each price as a *calibrated interval*, not a point: LightGBM quantile models wrapped in conformal prediction. "Calibrated" is the load-bearing word, and it is measured rather than assumed. On real NL prices, the nominal 90% interval covers the realized price **89.2% of the time** out-of-sample under a leakage-safe walk-forward, so the scenarios drawn from it inherit an honest spread instead of false confidence. Calibration alone is cheap (a wide interval covers everything), so accuracy is measured separately: at the interval edges the forecaster's pinball loss is **0.36x / 0.16x a seasonal-naive baseline's** under the same walk-forward (R2.5; below 1 is skill).

![Conformal price forecast on a held-out block: the shaded 90% interval, the point forecast, and the realized price; the interval widens where the price is volatile (heteroscedastic) and the realized price lands inside it close to the nominal 90% of the time.](docs/figures/example-forecast-intervals.svg)

Reproduce with `uv run --group forecast --group examples python examples/forecast_demo.py` (token, synthetic fallback otherwise).

A forecaster deployed against a live market decays, so the drift monitor (R2.1b) watches its trailing accuracy and, when it degrades, attributes *why*: a **regime shift** (the market moved and even a naive baseline degrades, so wait), **staleness** (the model fell behind a seasonal-naive, so retrain), or **miscalibration** (the point forecast is fine but the intervals stopped covering, so recalibrate). Separating these makes the alarm actionable rather than a bare "accuracy dropped." The decision is a map over two axes, with interval coverage as an orthogonal third trigger.

![Drift attribution map: the monitor's decision regions over the error ratio (forecaster vs. seasonal-naive MAE) and the input shift (PSI), each region coloured by what the real classifier returns there. Staleness (retrain) owns the whole high-ratio half regardless of input shift; regime shift (wait) is the high-PSI, low-ratio corner; miscalibration sits inside the healthy region because coverage is a third axis this map cannot show.](docs/figures/example-drift-regions.svg)

Reproduce with `uv run --group examples python examples/drift_demo.py` (synthetic by design: it renders the classifier's decision regions, not a market result).

A residual-path bootstrap then generates a few hundred price paths, and forward-selection reduction keeps the ~50 that best preserve the distribution (measured by Kantorovich distance), so the stochastic program stays small without discarding the tails that risk-aware dispatch cares about.

![Scenario reduction: Kantorovich distance to the full set vs. the number of paths kept (forward selection beats the k-means baseline), and the wall-clock cost of reducing, which together justify keeping ~50 of ~300.](docs/figures/example-scenario-reduction.svg)

That machinery only earns its place if it beats simply optimizing against the mean forecast. It does, and not only on a designed instance. Repeating the out-of-sample measurement over **every UTC day of a real NL quarter** (commitments fit on the trailing 28 days, then scored, fixed, on that day's realized prices) gives a **median per-window VSS of about +12 EUR** for the 2 MWh / 1 MW study asset, positive on **62% of 63 windows** (quartiles −8 to +33). The negative windows are real and reported: on a calm day the mean-value plan is fine, so the stochastic edge is a distribution, not a constant (R2.5).

![Per-window out-of-sample VSS on real NL 2024-Q2 days: a histogram of 63 windows straddling zero with its median clearly positive; the stochastic commitment usually, but not always, beats the mean-value plan out-of-sample.](docs/figures/example-vss-distribution.svg)

Reproduce with `uv run --group examples python examples/vss_study.py` (token, synthetic fallback otherwise).

The forecast layer is also held to a euro standard, not just a statistical one. The R2.5 **forecast-value baseline** feeds the same two-stage dispatch two scenario sets that differ only in the forecast behind them (conformal vs. seasonal-naive, forecaster refit walk-forward) and compares realized-path profit per window. Over the same 63 real windows the answer is a null, and it is reported as one: the FV distribution is **centred on zero** (median −0.9 EUR/window, 49% of windows positive, quartiles −41 to +31), despite the forecaster's clear statistical skill above. Single windows swing ±180 EUR either way, which is exactly why no single-window number is quoted. On this market and asset, the scenario spread plus intraday recourse hedge day-shape error well enough that point-forecast accuracy adds little further dispatch value; where the stochastic *structure* (the VSS above) earns real money, the fancier *forecast* does not yet, and the honest claim is exactly that.

![Per-window forecast value on real NL 2024-Q2 days: a histogram of 63 windows straddling zero with its median at roughly zero; conformal-forecast scenarios and seasonal-naive scenarios lead to plans of nearly equal realized value.](docs/figures/example-fv-distribution.svg)

The mechanism behind the VSS is the intraday recourse budget ρ: the value **rises then falls with ρ** (zero recourse and unlimited recourse both collapse to the mean-value plan; the value lives in between). Trading expected profit for downside protection traces a mean-CVaR frontier.

<table>
  <tr>
    <td width="50.7%"><img src="docs/figures/example-vss-curve.svg" alt="Value of the stochastic solution vs. the intraday recourse budget: zero at both ends, strictly positive in between, peaking where recourse is scarce enough to matter but ample enough to adapt."></td>
    <td width="50%"><img src="docs/figures/example-risk-return-frontier.svg" alt="Mean-CVaR risk/return frontier: raising the risk weight trades expected profit for a smaller downside (CVaR of loss), graded rather than a single point."></td>
  </tr>
</table>

The VSS and frontier figures are built from real NL day-ahead prices reshaped into daily scenarios; reproduce with `examples/stochastic_demo.py` (token, synthetic fallback otherwise). (The reduction figure above is synthetic by design: it demonstrates the algorithm's trade-off, not a market result.)

Solve time scales benignly with horizon (one binary plus a few continuous variables per period); [`examples/benchmark_scaling.py`](examples/benchmark_scaling.py) reports it (numbers are from a local run, so treat them as relative):

| Horizon | Periods | Median solve |
| --- | --- | --- |
| 1 day | 24 | ~9 ms |
| 1 week | 168 | ~29 ms |
| 1 month | 720 | ~120 ms |

The plotting dependency is optional: `uv sync --group examples` installs it.

### Why it holds (Release 2)

A schedule says *what* the battery does; the dual of the state-of-charge balance says *why*. That shadow price is the **water value**: the marginal worth of a stored MWh, borrowed from hydro-reservoir scheduling. It is flat while the battery is neither full nor empty and steps at a SoC bound, and it defines a **no-trade band** on price: charge only below the band, discharge only above it, hold in between. The band's width comes from round-trip loss and wear, not from the price, so an idle hour at a high price is explained rather than asserted, and each executed trade reports its breakeven slippage. `POST /explain` returns the schedule and this explanation from a single solve; the details are in [formulation.md §R2.4](docs/formulation.md#r24-shadow-price-explainability-derived-no-optimizer-change) and [ADR-0023](docs/decisions/0023-milp-dual-resolve-rule.md).

![Water value and no-trade band over a day: the shadow price of stored energy (flat within a run, stepping at SoC bounds) and the shaded price band it induces; at the €175 hour the price sits inside the band, so the battery idles and holds its charge for the later €200 peak.](docs/figures/example-water-value.svg)

Reproduce with `uv run --group examples python examples/explain_demo.py` (synthetic by design: it demonstrates the dual mechanism, not a market result).

## Architecture

The data flows one way, from a raw price feed to a schedule and its explanation. Whether prices are known splits the pipeline into the deterministic core (Release 1) and the forecasting-plus-stochastic stack (Release 2):

```mermaid
flowchart LR
    P["Day-ahead prices<br/>(ENTSO-E)"] --> G["Ingestion guard<br/>R1.4c"]
    G --> D{"Prices<br/>known?"}
    D -->|yes| OPT["Deterministic MILP<br/>R1.1 / R1.2"]
    D -->|no| FC["Conformal forecaster<br/>R2.1"]
    FC -.watched by.-> DM["Drift monitor<br/>R2.1b"]
    FC --> SC["Scenarios<br/>R2.2"]
    SC --> ST["Two-stage risk-aware<br/>+ intraday recourse<br/>R2.3"]
    OPT --> SCH["Optimal schedule"]
    ST --> SCH
    SCH --> EX["Water-value<br/>explanation<br/>R2.4"]
```

Under the hood the `bess` package is split into layers with a strict downward-only import direction (`api` at the top, `assets` at the base), enforced in CI by import-linter. The headline invariant is `optimizer ⊥ api`: the deterministic core never depends on the serving layer, so it stays testable in isolation. The full layer map and dependency diagram are in [docs/architecture.md](docs/architecture.md).

## How to read the docs

Start with [docs/architecture.md](docs/architecture.md) for the map, then dive into the math.

| Doc | What it is |
| --- | --- |
| [docs/formulation.md](docs/formulation.md) | **The math**: single source of truth for every constraint and objective term |
| [docs/conventions.md](docs/conventions.md) | Locked conventions: units, sign/metering, time, naming |
| [docs/glossary.md](docs/glossary.md) | Domain + optimization terms, each with a common-error note |
| [docs/market_reference.md](docs/market_reference.md) | How the BE/NL day-ahead market actually works |
| [docs/references.md](docs/references.md) | Source references, for the phases that use one |
| [docs/specs/](docs/specs/) | Per-phase work orders |

Assumes some familiarity with linear/integer programming; battery and power-market terms are defined in the [glossary](docs/glossary.md).

## Development

```bash
uv sync                       # environment + dependencies
uv run pytest                 # tests (golden + property gates)
ruff check . && ruff format . # lint + format
uv run mypy src               # static types
uv run lint-imports           # layering contract
```

The probabilistic forecaster (R2.1) is an optional dependency group: `uv sync --group forecast`, then `uv run --group forecast pytest tests/unit/test_forecaster_model.py`. On macOS it needs the OpenMP runtime; `.env.example` has the one-line setup.

## Serving

```bash
uv run uvicorn bess.api.app:app          # POST /dispatch, GET /health
docker build -t bess-dispatch . && docker run -p 8000:8000 bess-dispatch
```

`POST /dispatch` takes a price curve, a step, and a battery spec, and returns the optimal schedule. If the solver misses the latency budget (`BESS_LATENCY_BUDGET_S`, default 2.0 s), the circuit breaker serves the greedy schedule instead (`mode: "fallback_greedy"`) rather than failing the request; invalid input returns a structured 422.

## Data

The tests and CI use **synthetic** price series only, no real or third-party market data is committed (the ENTSO-E terms grant no public-redistribution right). Real Belgian/Dutch day-ahead prices are fetched at runtime via `bess.data.entsoe.fetch_day_ahead`, which wraps the [ENTSO-E Transparency Platform](https://transparency.entsoe.eu/) and caches to `data/cache/` (gitignored).

To run the live loader (and its token-gated integration test, skipped without a token), copy `.env.example` to `.env` and set `ENTSOE_API_TOKEN`. Any extra local setup (a CA bundle behind a TLS-intercepting proxy, the forecaster's OpenMP runtime) is documented in `.env.example`; it is operator setup, not code, and CI never touches the live API.

### Data reliability

A dispatch is only as trustworthy as the price it was computed from, so the data feed gets its own circuit breaker, distinct from the solver breaker above. `bess.data.ingestion_guard` classifies every fetch as **healthy**, **outage** (timeout / 5xx, i.e. no data), or **anomalous-but-present** (a frozen/stuck feed, a grid gap, a duplicate timestamp, or a value outside the EPEX SDAC clearing-price limits), and on either failure falls back to the last-known-good series rather than letting corrupt data reach the optimizer. A stale-but-present price is treated as *more* dangerous than an obvious outage because it fails silently, so a schedule solved on fallback data is reported as degraded, not healthy.

The checks key on feed *pathology*, not price *level*. Zero and negative day-ahead prices are legitimate in BE/NL (high-renewable windows), so a real solar-glut day is never mistaken for corruption.

The discriminator is the **value** a bit-identical run repeats, not the run's length. Excess supply collapses the clearing price onto the natural zero bid, so the market really does clear at exactly €0.00 for hours on end (NL and BE both did for 8 straight hours on 2024-03-24). It does not clear at an *arbitrary* cent repeatedly; that is a frozen feed. Keying on the value rather than the length lets the guard both leave a genuine zero-price day alone and catch a freeze three times faster.

![Ingestion guard: a feed frozen at an arbitrary price is rejected, and the dispatch runs on the trustworthy last-known-good series instead, so the overall provenance is reported as degraded rather than a silent optimal.](docs/figures/example-ingestion-guard.svg)

Reproduce with `uv run --group examples python examples/ingestion_guard_demo.py`.

## Known limitations and future work

The core is a deterministic, single-asset, day-ahead dispatch engine, and its scope boundaries are deliberate:

- **The deterministic core takes prices as known.** The core MILP solves against a given day-ahead curve. Price *uncertainty* is handled by the Release 2 stack layered on top (forecaster R2.1 → scenarios R2.2 → two-stage risk-aware dispatch with intraday recourse R2.3), whose value over a mean-forecast plan is the VSS reported above, and whose dispatch decisions are explained by the R2.4 shadow-price layer.
- **Day-ahead arbitrage only.** Intraday, imbalance, and ancillary-service markets (FCR / aFRR) are out of scope; the asset trades a single energy market.
- **No grid-connection / congestion constraint.** Dispatch is not capped at a connection-point limit. Adding a congestion or curtailment cap is the natural next physical constraint and is relevant to Dutch (TenneT) grid conditions.
- **Linear degradation only.** The degradation cost is linear in throughput (R1.2, the linear DoD-stress case); the nonlinear convex deep-cycle penalty, rainflow cycle-counting, and calendar aging are not modelled.
- **Single asset, single node.** No portfolio of assets and no network model.
