# ADR-0024: Day-ahead forecast features are aligned contemporaneously to the target

**Status:** Accepted
**Date:** 2026-07-24
**Supersedes / Superseded by:** None

## Context

R2.1c (spec `docs/specs/R2.1c-exogenous-fundamentals.md`) adds exogenous
fundamentals to the price forecaster: the ENTSO-E day-ahead **load forecast** and
**wind/solar generation forecast**, combined into residual load. This raises a
leakage question the R2.1 price features never faced.

R2.1's price features are lagged **≥ 24 h** on purpose: the *realized* price for a
target hour `t` on delivery day `D` is not known until the day-ahead auction clears,
so any same-day or future price would be look-ahead. If fundamentals were treated the
same way (lagged), they would lose most of their value, because the driver of `π_t` is
the load and renewables *at `t`*, not a day earlier.

But fundamentals are not realized quantities. ENTSO-E publishes the day-ahead load
forecast and the wind/solar generation forecast for the whole of day `D` **before the
day-ahead gate closes on `D−1`**. So at gate closure, the forecast value for target
hour `t` is already in the information set.

## Decision

Align day-ahead forecast features **contemporaneously to the target `t`** (the feature
row for `t` reads the forecast series at `t`), **not** shifted into the past like price
lags.

This is leakage-safe **if and only if the feature is the published day-ahead forecast,
never the realized actual.** The loaders therefore call the *forecast* ENTSO-E
endpoints (`query_load_forecast`, `query_wind_and_solar_forecast`) and never the
realized-actuals endpoint (`query_load`). Feeding realized generation/load at `t` would
be look-ahead and is forbidden.

## Consequences

- `make_features(fundamentals=…)` reindexes the fundamentals frame onto the target
  index by label (no shift). A target's fundamentals feature depends only on its own
  row, so no future (eventually-realized) row can enter.
- The forecaster conditions on the same day-ahead forecasts a real desk holds at gate
  closure, and inherits their error (the honest, realistic signal, not a hindsight one).
- The price-taker assumption is unchanged (formulation §R1.1 "Price-taker" note): the
  model still forecasts an exogenous price, now conditioned on more of the exogenous
  state.

## Failure mode

Passing realized actuals (or a forecast series accidentally shifted so a later value
lands on `t`) reintroduces look-ahead and would inflate apparent skill while failing in
production. Guards:

- **Golden oracle 4** (`test_oracle4_contemporaneous_alignment_not_lagged`): the feature
  at `t` equals the forecast at `t`, not `t−1`.
- **Leakage property** (`test_leakage_future_fundamentals_do_not_touch_past`): mutating
  fundamentals at/after `t+1` leaves the feature row at `t` unchanged.
- **Loader contract** (`test_load_forecast_calls_forecast_endpoint_and_normalizes`): the
  fetchers call the day-ahead *forecast* endpoints and never `query_load` (actuals).

## Alternatives considered

- **Lag fundamentals ≥ 24 h like price.** Rejected: discards the contemporaneous
  driver (residual load *at `t`*), which is most of the fundamentals' value, to guard a
  leakage that does not exist for a day-ahead-published forecast.
- **Use realized load/generation at `t`.** Rejected: look-ahead. It is not in the
  gate-closure information set and would not be available in production.
