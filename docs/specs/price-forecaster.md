# Spec: Price forecaster

**Status:** Implemented (gate green)
**Capability:** Price forecaster (`bess.forecaster`)
**Phases:** R2.1 conformal intervals (2026-07-01), R2.1b drift monitor (2026-07-01,
coverage added 2026-07-03), R2.1c exogenous fundamentals (2026-07-24)
**Depends on:** R1.4a (walk-forward discipline), R1.4b (the price series), R1.4c (the
fetch guard the fundamentals loaders reuse)

*Consolidated on 2026-07-28 from three work orders: the forecaster, the monitor that
watches it, and the features that condition it. All three live in one package and
share one contract, the calibrated interval. How the forecaster is **evaluated** is a
separate spec ([forecaster evaluation](forecaster-evaluation.md)), because that
phase found the instrument wrong rather than the model.*

## Objective

A probabilistic day-ahead price forecaster emitting calibrated **prediction
intervals**, not point estimates: LightGBM quantile learners wrapped in conformal
prediction so the intervals carry a distribution-free coverage guarantee. Conditioned
on **residual load**, the driver that actually sets the clearing price, and watched by
a rolling monitor that classifies *why* accuracy degraded so the alarm is actionable.

This is the uncertainty input the scenario layer samples from: forecast *uncertainty*,
not a single number.

## Formulation reference

**No optimizer delta.** No constraint, objective term, or efficiency placement changes.

The one new mathematical claim is the **conformal coverage guarantee**, and it does
belong in the formulation:
[`formulation-uncertainty.md` §R2.1](../formulation-uncertainty.md#r21-probabilistic-price-forecast-conformal-intervals-no-optimizer-change)
carries a brief, self-contained split-conformal and CQR summary with its
marginal-coverage property.

The drift monitor and the fundamentals features add **no formulation section**: PSI and
a naive-relative error ratio are standard statistics, and residual load as a
merit-order proxy is domain context, not a formulation claim.

## Governing reference

- **Governing (conformal prediction):** Angelopoulos & Bates, *A Gentle Introduction
  to Conformal Prediction and Distribution-Free Uncertainty Quantification*. Authority
  for split/inductive conformal, distribution-free **marginal** coverage under
  exchangeability, and conformalized quantile regression.
- **Secondary, pointers only:** Hyndman & Athanasopoulos on feature construction,
  exogenous regressors, and honest out-of-sample evaluation; Hastie, Tibshirani &
  Friedman for the boosted-tree learner.
- **None required** for the monitor or the fundamentals features: standard statistics
  and standard feature engineering (CLAUDE.md §1).
- **Notation:** house style wins. Prices stay `π_t` (€/MWh, grid-side) on the UTC
  schema; conformal's miscoverage `α` maps to `confidence_level = 1 − α`.

## Governing decisions

- [CQR over split conformal](../decisions/cqr-over-split-conformal.md): day-ahead
  prices are heteroscedastic, so a constant-width interval is miscalibrated
  *conditionally* even when marginally correct.
- [Drift classification precedence](../decisions/drift-classification-precedence.md):
  staleness, then regime, then miscalibration, each mapping to a different remedy.
- [Forecast feature alignment](../decisions/forecast-feature-alignment.md):
  day-ahead forecast features align contemporaneously to the target, which is
  leakage-safe **only** because the series is the published forecast.

## Design

### The interval

Fit the base learner on a proper-training split, conformalize on a disjoint,
strictly-later calibration split. **CQR is the default** (three LightGBM quantile
models: lower, upper, median), with split conformal kept as the simpler baseline the
coverage gate compares against. CQR gives **hour-adaptive** width, which matters
because evening peaks and scarcity hours are far more volatile than nights. The
trade-off is three base models instead of one, and coverage that is still only
marginal.

**Features are strictly lagged, so there is no leakage by construction.** Every price
feature at target `t` is a function of prices and calendar available before gate
closure for `t`. Lags are `[24, 48, 72, 168]` hours plus calendar (hour, weekday,
month, weekend, holiday), all derivable from the price series itself.

### Conditioning on fundamentals

A day-ahead price is the clearing point of an auction whose position on the
merit-order stack is set by **residual load** (`load − wind − solar`): high load with
low renewables pushes clearing up the stack toward expensive, volatile marginal units;
abundant renewables pushes it toward zero or negative. A price-lag model learns this
only second-hand, through yesterday's prices.

LightGBM is a tree ensemble and natively learns step and threshold functions, so given
residual load it approximates the supply curve's kinks empirically. That is the cheap
reduced form; a plant-level supply stack is out of scope.

**The leakage subtlety, which is correctness-critical.** Price features are lagged
≥ 24 h precisely because *realized* prices for day `D` are unknown until the auction
clears. **Fundamentals are different, and the difference is the whole point:** ENTSO-E
publishes the load and wind/solar forecasts for day `D` during `D−1`, so for a target
`t` on day `D` the day-ahead *forecast* at `t` exists before `t` occurs. These features
are therefore aligned **contemporaneously to `t`**, not shifted into the past.

This is leakage-safe **only because the feature is the published forecast, never the
realized actual.** Using `load_actual(t)` would be look-ahead and is forbidden.

> **Correction (2026-07-26).** This was originally justified by both series being
> published *before gate closure*. That holds for load (at least two hours before) but
> **not** for wind/solar, which Regulation (EU) 543/2013 Art. 14(1)(d) requires only by
> 18:00 on `D−1`, after the auction clears, with intraday revisions after. The
> contemporaneous alignment is unaffected for every use this project makes of it
> (decisions taken after day-ahead publication), but the "already in the gate-closure
> information set" justification is too strong for wind/solar. The corrected timing
> table is in the alignment decision record.

### The drift classification

Three signals over a trailing window, and a **precedence** that is the whole design:

1. `error_ratio = forecaster_MAE / naive_MAE ≥ 1.3` → **STALENESS**, so retrain.
   Checked first: even under a regime shift a healthy model should degrade *no worse
   than* a seasonal-naive baseline, so being materially worse than naive is
   model-specific decay.
2. else `psi ≥ 0.2` → **REGIME_SHIFT**, so accept or adapt. Inputs moved but the model
   is still competitive with naive.
3. else `coverage ≤ confidence_level − 0.10`, with at least 100 points →
   **MISCALIBRATION**, so recalibrate the conformal layer. Checked after regime so a
   genuine regime shift keeps its attribution.
4. else **HEALTHY**.

Coverage became a first-class signal by **amendment (2026-07-03)**, and the reason
matters: the monitor originally computed coverage and never classified on it, so the
forecaster's actual product went unmonitored. A model can hold `error_ratio ≈ 1` at low
PSI while its 90% band silently covers 75%, and because the scenario layer samples from
these intervals, an unmonitored coverage collapse propagates straight into the
stochastic layer. Coverage is **one-sided**: over-wide intervals are reported as a
signed deviation but never alarm.

**Honest gate framing.** Unlike the MILP's hand-solved oracles this is a **behavioral
regression gate**: the synthetic regime-shift and staleness patterns are *designed*,
and the classifier is checked to separate them. It proves the logic behaves as
specified, not a distribution-free truth. Stated plainly so it is not overclaimed.

## Parameters / configuration

| Item | Where | Default |
| --- | --- | --- |
| `confidence_level` (`1 − α`) | forecaster config | `0.9` |
| `method` | forecaster config | `"cqr"` (`"split"` as baseline) |
| lags (hours) | feature config | `[24, 48, 72, 168]` |
| rolling recalibration period | forecaster config | 7 days |
| LightGBM params | model config | modest, fixed seed |
| `use_fundamentals` | forecaster config | `False`, opt-in |
| fundamentals series | feature config | `residual_load` primary; `load_da`, `wind_da`, `solar_da` components |
| target alignment | feature config | contemporaneous to `t`, **not** lagged |
| missing-series policy | forecaster config | fall back to price+calendar, log a warning |
| `season` (naive lag, h) | monitor config | `168`, weekly |
| `psi_warn` | monitor config | `0.2` |
| `staleness_ratio` | monitor config | `1.3` |
| `psi_bins` | monitor config | `10` |
| `coverage_tol` | monitor config | `0.10`, wider than the pooled gate since a trailing window is noisier |
| `min_coverage_samples` | monitor config | `100`; below this coverage stays informational |

## Interfaces

```python
# src/bess/forecaster/  (imports bess.data only; feeds bess.scenarios)

@dataclass(frozen=True)
class IntervalForecast:
    point: pd.Series           # indexed by target UTC timestamp
    lower: pd.Series
    upper: pd.Series
    confidence_level: float    # nominal 1 − α

def make_features(
    prices: pd.Series, *, lags=DEFAULT_LAGS, calendar: bool = True,
    country: str | None = None,
    fundamentals: pd.DataFrame | None = None,   # load_da/wind_da/solar_da, index = target UTC
) -> pd.DataFrame:
    """Strictly-past-derived price features; every column at target t uses only info
    available before gate closure for t. When fundamentals is given, adds residual_load
    (load_da − wind_da − solar_da) and the raw components, aligned CONTEMPORANEOUSLY to
    each target t (day-ahead forecast, not lagged, not realized)."""

class PriceForecaster:
    def __init__(self, *, confidence_level=0.9, method="cqr",
                 use_fundamentals=False, **model_params): ...
    def fit(self, prices_train, fundamentals=None) -> "PriceForecaster": ...
    def predict_interval(self, prices_history, targets=None,
                         fundamentals=None) -> IntervalForecast: ...
    def recalibrate(self, recent_prices) -> None:
        """Refresh the conformal calibration on a rolling window; base model unchanged."""

# src/bess/data/entsoe.py  (mirrors fetch_day_ahead: guarded, cached, schema-validated)
def fetch_load_forecast(zone, start, end, *, api_token=None, cache_dir=None) -> pd.Series:
    """Day-ahead total load forecast, internal UTC schema, MW."""

def fetch_renewable_forecast(zone, start, end, *, api_token=None, cache_dir=None) -> pd.DataFrame:
    """Day-ahead wind + solar generation forecast, columns [wind_da, solar_da], MW."""

# src/bess/forecaster/drift.py  (pure numpy/pandas; runs without the forecast group)
class DriftStatus(StrEnum):
    HEALTHY = "healthy"
    REGIME_SHIFT = "regime_shift"
    STALENESS = "staleness"
    MISCALIBRATION = "miscalibration"

@dataclass(frozen=True, eq=False)
class DriftReport:
    status: DriftStatus
    forecaster_mae: float
    naive_mae: float
    error_ratio: float
    psi: float
    coverage: float | None
    reason: str | None

def psi(reference, current, *, bins: int = 10) -> float: ...
def seasonal_naive_forecast(prices, *, season: int = 168) -> pd.Series: ...
def classify_drift(*, forecaster_mae, naive_mae, psi_value, coverage=None,
                   staleness_ratio=1.3, psi_warn=0.2, confidence_level=0.9,
                   coverage_tol=0.10, n_coverage=None,
                   min_coverage_samples=100) -> DriftReport:
    """Pure classifier over the trailing-window metrics, the precedence above."""

class DriftMonitor:
    def assess(self, realized, point, naive, *, lower=None, upper=None) -> DriftReport:
        """Takes plain arrays, so it is decoupled from a live forecaster and testable
        without the forecast group."""
```

**MAPIE 1.x contract** (verified end-to-end against `mapie==1.4.1`, `lightgbm==4.6.0`).
MAPIE will **not** accept a single LightGBM for CQR, since it cannot set the quantile
param: pass **three prefit quantile models in order `[lower(α/2), upper(1−α/2),
median]`** with `prefit=True`. That three-model pattern is the implementation
contract, verified end to end (toy coverage 0.95 split, 0.91 CQR).
MAPIE emits a benign feature-names warning when fed numpy after fitting on a named
frame; feed consistent types throughout. Pin the major version, since the API changed
at 1.0.

**Layering.** `bess.forecaster` sits in the forecast-feed contract
(`stochastic ← scenarios ← forecaster`). It **may** import `bess.data` (a leaf); it
must **not** import `scenarios`, `stochastic`, or the serving chain.

**Operator setup, local macOS.** LightGBM needs the OpenMP runtime (`brew install
libomp`), not bundled in its macOS wheel. Operator setup, not code, like the CA bundle.
Linux CI links `libgomp` already.

## Build tasks

- [x] `forecast` dependency group (`lightgbm`, `mapie`, `scikit-learn`, `holidays`),
      MAPIE major pinned.
- [x] `make_features`: lagged prices + calendar, with a leakage unit test asserting no
      feature at `t` depends on a price at or after gate closure for `t`.
- [x] `forecast.py`: LightGBM quantile base learners; MAPIE CQR and split conformal
      behind one `method` switch; `fit` / `predict_interval` / `recalibrate`.
      *(`recalibrate` shipped untested and raised on every call, because MAPIE forbids
      a second `conformalize` on one estimator, which made the monitor's
      recalibrate-don't-retrain response unreachable. Fixed 2026-07-26 by rewrapping
      the prefit base learners in a fresh conformal estimator, with unit tests on both
      methods.)*
- [x] Walk-forward coverage harness reusing the backtest's expanding-window discipline.
- [x] `drift.py`: the four statuses, `psi`, `seasonal_naive_forecast`,
      `classify_drift`, `DriftMonitor`. Pure numpy and pandas, no new dependency, no
      new CI step.
- [x] Structured log line per non-healthy assessment, so the *type* is grep-visible,
      mirroring the ingestion guard.
- [x] **Fetch and print a real sample first** (repo guardrail): probed the ENTSO-E load
      and wind/solar forecast endpoints for real NL 2024-06. Resolved schema recorded
      in the loader: load is `Forecasted Load` in MW at 15-min; wind/solar is
      `Solar`, `Wind Offshore`, `Wind Onshore` in MW at 15-min, both zone-local. The
      day-ahead price is hourly, so the feeds are mean-resampled to the hourly grid.
- [x] `fetch_load_forecast` / `fetch_renewable_forecast` / `fetch_fundamentals`
      mirroring `fetch_day_ahead`; `wind_da` sums offshore and onshore.
- [x] Extend `make_features` with `fundamentals`, aligned contemporaneously (reindex by
      label, no shift), dropped consistently in the warm-up.
- [x] Thread `use_fundamentals` through fit, predict, recalibrate, and both
      walk-forward harnesses; the default-off path is byte-identical.
- [x] Graceful degradation: `use_fundamentals=True` with none supplied falls back to
      price+calendar and logs a warning.
- [x] Token-gated integration on real ENTSO-E, skipped in CI, nothing committed.

## Golden oracles

Feature construction is exact arithmetic, so these are un-fakeable rather than
statistical.

| # | inputs | expected | why this case |
| --- | --- | --- | --- |
| 1 | `load_da=[100,120]`, `wind_da=[30,10]`, `solar_da=[20,0]` at `t0,t1` | `residual_load = [50, 110]` | pins the residual-load arithmetic exactly |
| 2 | same, but mutate the *realized* load at `t1` | `residual_load` at `t1` unchanged | pins leakage-safety: features read the forecast, never the actual |
| 3 | `fundamentals=None` | feature matrix byte-identical to the price+calendar model | pins the opt-in contract |
| 4 | forecast at `t` aligned to target `t` | `residual_load` at row `t` equals the forecast for `t`, not `t−1` | pins contemporaneous, not lagged, alignment |

Forecasting itself has **no exact oracle**. The un-fakeable anchors are coverage on
data the model did not calibrate on, and deterministic reproducibility.

## Property tests

- **Interval ordering:** `lower ≤ point ≤ upper` at every target, always.
- **Monotone in confidence:** a higher confidence level yields intervals no narrower
  than a lower one.
- **No leakage (price):** features at `t` are invariant to any mutation of prices at or
  after gate closure for `t`.
- **No leakage (fundamentals):** features at `t` are invariant to any mutation of the
  *realized* load, wind, or solar at `t` or later, and depend only on the published
  forecast.
- **Opt-in identity:** with fundamentals off, outputs are bit-identical on the same
  seed and inputs.
- **Residual-load identity:** `residual_load == load_da − wind_da − solar_da` row-wise.
- **No new NaNs** beyond the lag warm-up.
- **Determinism:** fixed seed and inputs give bit-stable point and interval outputs.
- **Graceful degradation:** with fundamentals absent, a valid equivalent forecast is
  produced and the fallback is logged.
- **Drift discrimination:** an injected regime shift (mean-level jump, high PSI, both
  errors rising together so the ratio is ≈ 1) and injected staleness (inputs stable,
  low PSI, forecaster residuals inflated while naive tracks) must classify
  **differently and correctly**.
- **Miscalibration discrimination:** an episode with a tracking point model, stable
  inputs, and too-tight intervals classifies MISCALIBRATION, not HEALTHY and not
  STALENESS; the mirror case with correctly wide intervals classifies HEALTHY. This
  proves coverage is a live signal rather than a passenger.
- **Classifier precedence** holds when signals co-fire; a coverage breach below
  `min_coverage_samples` stays HEALTHY; over-coverage never flags.
- **PSI sanity:** `psi(x, x) ≈ 0`, growing monotonically as a distribution shifts.

## Acceptance gate

*Blocks:* scenario generation. Every box must pass.

These are **statistical** gates, like the ingestion classifier's, not the MILP's
un-fakeable arithmetic. Stated so they are not overclaimed.

- [x] **Coverage (headline):** empirical coverage of the interval at nominal `0.9`
      lands within `0.9 ± 0.05`, that is empirical coverage in `[0.85, 0.95]`, decided by
      whether a day-block bootstrap interval can rule that claim out. Re-validated on real ENTSO-E.
- [x] **Coverage preserved under fundamentals (hard):** **0.894**, 95% CI
      [0.876, 0.912], against nominal 0.90. Fundamentals do not break calibration.
      *(Re-measured live 2026-07-28 on NL 2021 to 2025, 260 out-of-sample days, shipped
      capacity. Originally reported as 0.899 on Feb to Jun 2024 with three contiguous
      folds and 120 trees.)*
- [x] **Accuracy improves (headline, honest):** walk-forward pinball loss with
      fundamentals is **−13.4%** versus price+calendar (4.770 → 4.132), reported with
      provenance. This was *not* asserted positive in advance; the gate asserts only
      **no material regression**, which guards misalignment, so a null on another asset
      would be reported rather than suppressed.
      *(Originally reported as −16.6%. That figure came from 15 test days inside a
      single fortnight of May 2024 at 120 trees; re-measured across 260 days spanning
      2021 to 2025 at shipped capacity the effect **shrinks but holds**. The absolute
      pinball levels are not comparable between runs, since the spans differ in
      volatility; only the relative delta is.)*
- [x] **Reproducibility (golden-analog):** fixed seed and inputs give bit-stable
      outputs, so the pipeline is regression-testable.
- [x] **Feature-alignment goldens** 1 to 4 pass exactly.
- [x] **Drift discrimination and miscalibration discrimination** properties pass.
- [x] `ruff`, `format`, `mypy`, `lint-imports`, and docs-lint clean; all other gates
      unchanged.

## Out of scope

- **Weather features.** Superseded by generation forecasts, which already fold
  hub-height wind and irradiance into the quantity that sets the stack, and share
  ENTSO-E's provider and timing. Raw weather would be a separate provider and licensing
  path for a driver already summarized.
- **Gas, carbon, and cross-border flow features.** Real drivers, but different
  providers and messier timing.
- **An explicit plant-level merit-order model.** Fuel prices, unit marginal costs,
  capacities, outages: a different acquisition and modelling scope. The tree plus
  residual load is the intended substitute. An explicit reduced-form stack transform
  (a binned `price ≈ f(residual_load)` prior) is **deferred**: add it only if the
  fitted partial dependence visibly under-fits the kink on real data.
- **Extreme-value tail on scenarios.** Conditioning on residual load is the
  *prerequisite* for a conditional spike model, but fitting the tail lives in the
  scenario layer. Recorded so the dependency ordering is on record.
- **Automatic retraining or recalibration triggers.** The monitor classifies and logs;
  wiring it to fire a retrain is a follow-on, since silent auto-retrain is itself a
  failure mode.
- **Adaptive conformal (ACI) for distribution shift.** The monitor detects; it does not
  adapt the intervals online.
- **Multivariate or feature-level drift attribution.** PSI on the price distribution
  only.
- **Alerting transports.** A log line; wiring a sink is ops config.
- **Multi-zone joint forecasting, hierarchical reconciliation, deep-learning
  forecasters.** A boosted-tree baseline is the scope; conformal is the differentiator,
  not the base learner.

## Decisions

**The interval (reviewed 2026-07-01).**

1. **Method.** **Resolved: CQR default**, split conformal kept as the compared
   baseline, justified by day-ahead heteroscedasticity. Bare quantile regression gives
   quantiles but **no finite-sample coverage guarantee**, so it is the CQR base learner
   rather than the deliverable; bootstrap and Gaussian residual intervals are heavier
   and distribution-assuming.
2. **Conformal summary in the formulation.** **Resolved: yes, a brief section**,
   summarizing the coverage guarantee only.
3. **Dependency weight.** **Resolved: behind an optional `forecast` group**, so the
   core install and the main CI job stay lean.
4. **Coverage tolerance.** **Resolved: `0.9 ± 0.05`** (empirical in `[0.85, 0.95]`), not tuned to pass.
   *(Amended 2026-07-28: the justification originally given, "the walk-forward
   calibration-set size", named the wrong quantity. Coverage sampling noise is governed
   by the **test** set, whose indicators cluster within a day, so on the original 15
   test days the band was narrower than the noise of the statistic it gated. The band
   survives as the claim; what changed is that the gate now decides by whether a
   day-block bootstrap interval can rule it out.)*
5. **Rolling statistics.** The original feature line promised them and they were never
   built; `make_features` implemented lags and calendar only. **Resolved
   (2026-07-28): not back-filled silently.** They are a model change and were scoped to
   their own phase.

**The monitor (reviewed 2026-07-01, amended 2026-07-03).**

6. **Naive baseline.** **Resolved: seasonal-naive at 168 h**, the honest strong
   benchmark for hourly power prices, since it respects weekday and weekend structure.
7. **Precedence when signals co-fire.** **Resolved: staleness wins.** Worse-than-naive
   is model-specific decay regardless of input shift.
8. **Thresholds.** **Resolved:** `psi_warn = 0.2` (standard), `staleness_ratio = 1.3`,
   both configurable.
9. **Coverage as a third state.** **Resolved (2026-07-03):** add it, checked *after*
   regime so a genuine regime shift keeps its attribution, one-sided, guarded by a
   minimum sample count. The alternative, a one-sided binomial test on the miss count,
   is more principled on small windows but more machinery than a monitoring phase
   warrants.

**Fundamentals (reviewed 2026-07-24).**

10. **Which series enter the matrix.** *Proposed:* residual load plus the raw
    components. **Resolved: both.** Residual load carries the merit-order signal; the
    components let the model split economically distinct regimes (solar-driven midday
    troughs versus wind-driven overnight ones) that share a residual-load value. Cheap
    once the series are fetched, and the identity property pins them together anyway.
11. **Contemporaneous alignment.** **Resolved: yes**, promoted to its own decision
    record. This is the single correctness-critical choice in the phase, pinned by
    oracles 2 and 4 and the leakage-invariance property.
12. **Source boundary.** **Resolved: ENTSO-E only, day-ahead-published series only**,
    reusing the existing client, token, cache, and guard. One provider, one timing
    convention, no new licensing path: the boundary that keeps the phase cheap.
13. **Fundamentals rather than raw weather.** **Resolved:** generation forecasts
    already encode weather into the quantity that sets the stack, and share the
    provider and timing. This supersedes the earlier "weather as a later phase" idea.
14. **Missing-fundamentals policy.** **Resolved: graceful fallback**, matching the
    serving breaker and ingestion-guard posture, since a degraded-but-valid forecast
    beats no forecast.
