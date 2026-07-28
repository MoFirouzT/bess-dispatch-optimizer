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

But fundamentals are not realized quantities: they are published for the whole of day
`D` during `D−1`, so a value for target hour `t` exists before `t` occurs.

**The two series do not arrive together, and only one is guaranteed before gate
closure** (Regulation (EU) 543/2013; corrected 2026-07-26, see "Publication timing"
below). The load forecast lands before the auction; the wind/solar forecast is only
mandated afterwards.

### Publication timing

Deadlines are regulatory minima; TSOs routinely publish earlier, but a historical fetch
cannot tell whether they did.

| Time (CET) | Event | Source |
| --- | --- | --- |
| `D−1` 10:00 | Load forecast (at least 2 h before gate closure) | Art. 6(1)(b) |
| `D−1` 12:00 | Day-ahead gate closure | SDAC |
| `D−1` ~12:45 | Day-ahead prices published | SDAC |
| `D−1` 18:00 | Wind and solar forecast | Art. 14(1)(d) |
| `D` 07:00 | At least one wind/solar update; further intraday updates | Art. 14(1)(d) |

So the wind/solar forecast is guaranteed only *after* the auction it is meant to help
predict, and it is then revised repeatedly during delivery.

## Decision

Align day-ahead forecast features **contemporaneously to the target `t`** (the feature
row for `t` reads the forecast series at `t`), **not** shifted into the past like price
lags.

This is leakage-safe **if and only if the feature is the published day-ahead forecast,
never the realized actual.** The loaders therefore call the *forecast* ENTSO-E
endpoints (`query_load_forecast`, `query_wind_and_solar_forecast`) and never the
realized-actuals endpoint (`query_load`). Feeding realized generation/load at `t` would
be look-ahead and is forbidden.

**Scope of that safety, per the timing above.** Alignment is sound for a decision taken
*after* day-ahead publication, which is every use the project currently makes of the
forecaster. It is **not** established for a decision taken at or before gate closure
(the R2.6 bid-curve setting): there the wind/solar forecast may not yet exist, and the
value a historical fetch returns may be a later revision. Treat pre-gate-closure use as
an open question, not as covered by this ADR.

## Consequences

- `make_features(fundamentals=…)` reindexes the fundamentals frame onto the target
  index by label (no shift). A target's fundamentals feature depends only on its own
  row, so no future (eventually-realized) row can enter.
- The forecaster conditions on published forecasts rather than outcomes, so it inherits
  their error (the honest, realistic signal, not a hindsight one). For load this is the
  same information a desk holds at gate closure; for wind/solar it may be a sharper,
  later vintage, so the inherited error is a lower bound on the live one.
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

**Unguarded: forecast vintage.** All three guards test *alignment* (no shift along the
time axis) and cannot see *which revision* of a forecast a timestamp carries. The
Transparency Platform serves a stored value per timestamp, and Art. 14(1)(d) mandates
intraday updates, so a historical wind/solar fetch may return a revision made during
delivery rather than the `D−1` publication. Nothing in the series reveals this, so it is
recorded as a known limitation rather than a test. Bounding it needs either a
vintage-aware retrieval or an ablation measuring how much of the R2.1c pinball gain
survives on load alone (unambiguously pre-gate-closure). Neither is done.

## Alternatives considered

- **Lag fundamentals ≥ 24 h like price.** Rejected: discards the contemporaneous
  driver (residual load *at `t`*), which is most of the fundamentals' value, to guard a
  leakage that does not exist for a day-ahead-published forecast.
- **Use realized load/generation at `t`.** Rejected: look-ahead. It is not in the
  gate-closure information set and would not be available in production.
