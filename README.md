# bess-dispatch-optimizer

Optimal day-ahead dispatch for a grid-scale **battery energy storage system (BESS)** in the Belgian/Dutch power market. Given a day-ahead price curve and a battery's physical limits, it computes the charge/discharge schedule that maximizes arbitrage revenue net of cell degradation — as a deterministic mixed-integer linear program (MILP).

## What problem this solves

A battery earns money by **buying low and selling high**: charge when day-ahead electricity is cheap, discharge when it is expensive. The catch is that every cycle ages the cell, charging and discharging each lose energy (round-trip efficiency < 1), and the schedule must respect power, energy, and ramp limits. This project formulates that trade-off precisely and solves it to optimality, then measures how much of the theoretical maximum a realistic, no-look-ahead policy actually captures.

## Status

Release 1 (deterministic core) is **complete**, gated by golden + property tests:

- **R1.1** — deterministic MILP dispatch core
- **R1.2** — convex piecewise-linear degradation cost
- **R1.3** — pre-flight feasibility checks
- **R1.4** — walk-forward backtest with greedy / rolling / perfect-foresight baselines, plus a live ENTSO-E day-ahead loader (BE/NL)
- **R1.5** — FastAPI dispatch service with a graceful-degradation circuit breaker (greedy fallback on solver timeout), Dockerized

Release 2 (forecasting, stochastic optimization, recourse, explainability) is planned — see [docs/architecture.md](docs/architecture.md).

## How to read the docs

Start with [docs/architecture.md](docs/architecture.md) for the map, then dive into the math.

| Doc | What it is |
|---|---|
| [docs/formulation.md](docs/formulation.md) | **The math** — single source of truth for every constraint and objective term |
| [docs/conventions.md](docs/conventions.md) | Locked conventions: units, sign/metering, time, naming |
| [docs/glossary.md](docs/glossary.md) | Domain + optimization terms, each with a common-error note |
| [docs/market_reference.md](docs/market_reference.md) | How the BE/NL day-ahead market actually works |
| [docs/references.md](docs/references.md) | The governing textbook reference for each phase |
| [docs/specs/](docs/specs/) | Per-phase work orders |

Assumes some familiarity with linear/integer programming; battery and power-market terms are defined in the [glossary](docs/glossary.md).

## Development

```bash
uv sync                       # environment + dependencies
uv run pytest                 # tests (golden + property gates)
ruff check . && ruff format . # lint + format
uv run lint-imports           # layering contract
```

## Serving

```bash
uv run uvicorn bess.api.app:app          # POST /dispatch, GET /health
docker build -t bess-dispatch . && docker run -p 8000:8000 bess-dispatch
```

`POST /dispatch` takes a price curve, a step, and a battery spec, and returns the optimal schedule. If the solver misses the latency budget (`BESS_LATENCY_BUDGET_S`, default 2.0 s), the circuit breaker serves the greedy schedule instead (`mode: "fallback_greedy"`) rather than failing the request; invalid input returns a structured 422.

## Data

The tests and CI use **synthetic** price series only — no real or third-party market data is committed (the ENTSO-E terms grant no public-redistribution right). Real Belgian/Dutch day-ahead prices are fetched at runtime via `bess.data.entsoe.fetch_day_ahead`, which wraps the [ENTSO-E Transparency Platform](https://transparency.entsoe.eu/) and caches to `data/cache/` (gitignored).

To run the live loader (and its token-gated integration test, skipped without a token), copy `.env.example` to `.env` and set `ENTSOE_API_TOKEN`. On a network with a TLS-intercepting proxy, uv's bundled Python also needs the trust roots exported to a CA bundle (`REQUESTS_CA_BUNDLE` / `SSL_CERT_FILE`); the steps are in `.env.example`. This is operator setup, not code, and CI never touches the live API.

## Known limitations and future work

Release 1 is a deterministic, single-asset, day-ahead dispatch engine. Its scope boundaries are deliberate:

- **Prices are taken as known.** The optimizer assumes the day-ahead curve is given; it does not forecast prices or model their uncertainty. Probabilistic forecasting and a two-stage stochastic / recourse layer are Release 2, which is where the cross-day arbitrage gap measured by the backtest (`V* − V_roll`) is meant to be captured.
- **Day-ahead arbitrage only.** Intraday, imbalance, and ancillary-service markets (FCR / aFRR) are out of scope; the asset trades a single energy market.
- **No grid-connection / congestion constraint.** Dispatch is not capped at a connection-point limit. Adding a congestion or curtailment cap is the natural next physical constraint and is relevant to Dutch (TenneT) grid conditions; it is named future work, not yet built.
- **Convex degradation only.** The degradation cost is a convex piecewise-linear curve (R1.2); rainflow cycle-counting and calendar aging are not modelled.
- **Single asset, single node.** No portfolio of assets and no network model.
