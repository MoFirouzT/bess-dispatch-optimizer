# Spec R2.1e. Target normalization, rolling-stat features, cyclical season encoding

**Status:** Implemented (2026-07-28; gate green, results below)
**Release:** R2  **Depends on:** R2.1 (the forecaster), R2.1c (fundamentals features), R2.1d (the evaluation harness this phase is measured on)
**Phases:** R2.1e (2026-07-28)

## Objective

Make the forecaster's **conditional** calibration good, not just its marginal
calibration, by predicting a de-levelled and de-scaled target instead of the raw
price. Secondary: add the rolling-statistic features R2.1 promised and never
built, and re-apply the cyclical season encoding that is only valid now that the
training window spans a full year.

This is the model-change phase R2.1d deliberately sequenced itself before. It is
measured entirely on R2.1d's harness; it adds no evaluation machinery of its own
beyond one conditional-coverage statistic.

## Why this, and why now

R2.1d rebuilt the measurement and the marginal coverage claim came through intact
(NL 2021 to 2025, 260 test days: cqr **0.900**, 95 percent interval
**[0.883, 0.916]**; BE **0.903**). The weakness it exposed is elsewhere.

1. **Per-fold coverage runs 0.617 to 1.000.** Marginal coverage is essentially
   exact while individual folds are badly miscalibrated in both directions. That
   is the textbook signature of a marginal-only guarantee, which
   [`formulation-uncertainty.md` §R2.1](../formulation-uncertainty.md#r21-probabilistic-price-forecast-conformal-intervals-no-optimizer-change)
   already lists under "considered but out of scope". R2.1d turned it from an
   acknowledged caveat into a measured number.
2. **The property CQR was chosen for has never been tested.** [CQR over split conformal](../decisions/cqr-over-split-conformal.md) selected
   conformalized quantile regression over split conformal specifically to get
   **hour-adaptive** interval width, because evening peaks are far more volatile
   than nights. No gate anywhere checks coverage *conditional on hour of day*, so
   the central design decision of R2.1 rests on an untested claim.
3. **A stale fit still cannot cross a season boundary.** Out-of-season coverage is
   **0.788** (cqr) and **0.816** (split) against nominal 0.9, pinned by
   `test_coverage_gate_does_not_transfer_out_of_season`. R2.1d established that
   more history does not fix this: the training-window sweep on identical test
   days gave flat accuracy (pinball 3.574 / 3.674 / 3.532 / 3.711 at 90 / 180 /
   365 / 730 days) and *wider* intervals at longer windows.

The mechanism behind all three is the same. A gradient-boosted tree cannot predict
outside the range of its training targets, and it splits on raw price levels whose
distribution moves under it. NL yearly means over the span run 102.97, 241.88,
95.81, 77.28, 86.34 EUR/MWh, roughly a 3x spread. So the model spends capacity
memorizing a level that is not stable, and its conformal residuals inherit that
non-stationarity, which is exactly the exchangeability violation the coverage
guarantee rests on.

## Design

**Predict a standardized target.** For target time `t`, define a baseline level
and scale from prices strictly available at gate closure, then fit on

  `z_t = (price_t - level_t) / scale_t`

and invert the prediction and both interval bounds with
`price = level_t + scale_t * z`.

**Why this preserves the coverage guarantee exactly.** At prediction time
`level_t` and `scale_t` are known constants (they are functions of lagged prices
alone), so `z -> level_t + scale_t * z` is a **known, strictly increasing affine
map** with `scale_t > 0`. Coverage therefore transfers point by point:
`P(price in [level + scale*lo, level + scale*hi]) = P(z in [lo, hi]) >= 1 - alpha`.
Nothing about the conformal argument changes; the guarantee is inherited, not
re-derived. What *does* change is that the interval's width in price space becomes
proportional to `scale_t`, so it widens automatically in volatile periods. That is
the standard locally-weighted or normalized-nonconformity construction, and it is
the direct attack on finding 1 above.

**Why additive, never a ratio or a log.** Build task 0 of R2.1d measured the share
of hours at or below zero across the span: 0.8, 1.0, 3.6 and 5.2 percent by year,
with a minimum of minus 500 EUR/MWh. Any multiplicative de-levelling is undefined
or sign-flipping on those hours. This is a measured constraint, not a stylistic
preference.

**Features are normalized by the same pair.** Lag features become
`(price_{t-h} - level_t) / scale_t`. Leaving them raw while normalizing the target
would leave the tree splitting on a moving quantity to predict a stationary one,
which is the worst of both. Calendar features are unaffected. Fundamentals stay in
physical units (MW): they are bounded quantities without the price's level drift,
and normalizing them would entangle two unrelated scales.

**Rolling statistics arrive as a by-product.** `level_t` and `scale_t` are exactly
the rolling mean and standard deviation R2.1's scope section promised, so they are
also exposed as features rather than only as a transform, together with a
prior-day mean and a same-hour trailing-week mean.

**Cyclical season encoding, re-applied under its precondition.** Replacing `month`
with day-of-year sine and cosine was tried in R2.1 and reverted, correctly: on a
4-month window the pair is out of range for unseen dates and is ambiguous around
the solstice. With R2.1d's fixed 365-day rolling training window every fit spans a
full year, which is the condition the reverted experiment lacked. The rationale
recorded inline in `bess.forecaster.features` is updated in the same change so the
revert history stays legible.

## Formulation reference

**No optimizer delta.** No constraint, variable, objective term, or efficiency
placement changes; `docs/formulation.md` is untouched.

`formulation-uncertainty.md` §R2.1 gains a short paragraph for the normalized target: the
affine-inversion argument above and the resulting locally-adaptive width, stated
as an inherited property rather than a new guarantee. Changelog entry in the same
change (CLAUDE.md §1).

## Parameters / configuration

| Item | Where | Default | Notes |
| --- | --- | --- | --- |
| `normalize_target` | forecaster config | `False` | opt-in; `False` is byte-identical to R2.1d |
| baseline window | feature config | 168 h (7 days) | ends at `t - 24 h`, so strictly pre-gate-closure |
| level statistic | feature config | mean over the window | all hours, 168 samples |
| scale statistic | feature config | standard deviation over the window | same window |
| scale floor | feature config | 1.0 EUR/MWh | prevents division blow-up on a flat window |
| `season_encoding` | feature config | `"cyclical"` | `"month"` keeps R2.1 behavior |
| rolling-stat features | feature config | on when `normalize_target` | prior-day mean, same-hour trailing-week mean |

## Interfaces

Additions to `bess.forecaster.features` and `bess.forecaster.forecast`. No new
module, no layering change, no new dependency.

```python
def rolling_baseline(
    prices: pd.Series, *, window_h: int = 168, gap_h: int = 24, scale_floor: float = 1.0
) -> pd.DataFrame:
    """Level and scale for each target, from prices strictly before `t - gap_h`.

    Returns columns `level` and `scale` on the price index. `scale` is floored so
    the inverse transform is always well defined. Leakage-safe by construction:
    the window ends `gap_h` hours before the target."""


def make_features(
    prices, *, lags=..., calendar=True, country=None, fundamentals=None,
    normalize=None, season_encoding="month", rolling_stats=False,
) -> pd.DataFrame:
    """`normalize` takes a `rolling_baseline` frame; when given, lag columns are
    expressed in standardized units. `season_encoding="cyclical"` swaps `month`
    for day-of-year sine and cosine."""
```

`PriceForecaster` gains `normalize_target: bool = False`. When set, `fit` builds
the baseline, standardizes the target, fits and conformalizes in standardized
space, and `predict_interval` inverts point, lower and upper with the target's own
`level` and `scale`. `IntervalForecast` is unchanged: callers still receive prices.

## Build tasks

- [x] **Baseline first.** Measure and record hour-of-day conditional coverage for
      the current model on R2.1d's span, both methods. Without this number the
      phase has nothing to improve against, and [CQR over split conformal](../decisions/cqr-over-split-conformal.md)'s adaptive-width claim
      stays untested either way.
- [x] Add a conditional-coverage statistic to the R2.1d harness: coverage per
      hour-of-day bucket, plus the maximum absolute deviation from nominal across
      buckets, carried on the existing result object.
- [x] `rolling_baseline`, pure pandas, with the leakage gap.
- [x] `make_features` gains `normalize`, `season_encoding`, `rolling_stats`;
      `normalize=None` and `season_encoding="month"` stay byte-identical.
- [x] `PriceForecaster.normalize_target`: standardize on fit, invert on predict.
      Verify the inversion is exact to floating point on both interval bounds.
- [x] Re-run the R2.1d training-window sweep **under normalization**. This is the
      discriminating test for whether gas-crisis history is usable as training
      data: under the raw target 730 days was the worst window measured, and if
      de-levelling is doing what it claims that ordering should change. Report the
      result either way.
- [x] Re-measure every R2.1d gate under the new model and restate the claims.
- [x] Resolve the out-of-season pin (see open question 4).
- [x] `ruff` / `format` / `mypy` / `lint-imports` / `lint_docs` clean; every gate
      outside the R2.1 line unchanged.


## Measured results (2026-07-28)

All on NL, R2.1d's harness (52 folds of 5 days, 260 evaluated test days), CQR unless
stated. Sweep rows use **identical test days** (first fold 2023-01-01) so window
length is not confounded with test period, the confound R2.1d found the first time.

**1. Conditional coverage improves on the shipped configuration.** Maximum
hour-of-day coverage deviation moves **0.0653 to 0.0498** (cqr, 365-day window), a
24 percent reduction, while marginal coverage holds (0.9003 to 0.9008) and mean width
*narrows* slightly (138.3 to 134.8 EUR/MWh). Better conditional calibration and
tighter intervals together, which is the outcome this phase was aimed at.

*A correction worth keeping visible:* an earlier reading of this line called it a
null (0.0653 to 0.0622). That number came from a configuration bundling all three
changes, including the cyclical season encoding that finding 3 below shows is
harmful. Once the encoding is dropped, which is what ships, the improvement is
roughly four times larger. The lesson is the ordinary one about compound changes:
measuring a bundle measures the bundle, not the part worth keeping.

**2. The payoff is at a longer window, and it is not a null.** Normalization
**flips the ordering of the training-window sweep**:

| train_days | pinball raw / norm | max hour dev raw / norm | width raw / norm |
| --- | --- | --- | --- |
| 90 | 3.574 / 3.761 | 0.0776 / 0.1278 | 96.8 / 101.8 |
| 180 | 3.674 / 3.796 | 0.0699 / 0.0853 | 100.6 / 105.1 |
| 365 | 3.532 / **3.419** | 0.0846 / **0.0691** | 107.0 / 99.8 |
| 730 | 3.711 / **3.411** | 0.0660 / 0.0691 | 106.0 / **96.1** |

Under the raw target 730 days was the **worst** window R2.1d measured. Under
normalization it is the **best**, with the narrowest intervals. There is a clean
crossover at 365 days: normalization *hurts* on short windows and helps on long
ones, which fits the mechanism (a 90-day window is already roughly stationary, so
de-levelling only adds estimation noise, while a 730-day window carries the regime
drift de-levelling exists to remove). **This is the discriminating test the phase was
designed around, and it came out positive: gas-crisis history is harmful as training
data under a raw target and useful under a de-levelled one.**

**3. The cyclical season encoding is measured and NOT shipped.** Adding it to
normalization costs accuracy at both windows (pinball 3.419 to 3.509 at 365 days;
3.411 to 3.532 at 730) and raises quantile crossing (2 to 37 clipped points at 730).
The phase's premise was that a full-year training window would rescue the encoding
R2.1 reverted. Measured on a proper instrument, it does not. `season_encoding`
therefore stays `"month"`, and the R2.1 revert now rests on a real measurement rather
than on a 4-month-window artifact.

**4. Rolling-stat features are a trade, and are not shipped by default.** They give
the best conditional coverage measured (max hour deviation 0.0614 at 365 days, 0.0575
at 730) but cost pinball (3.419 to 3.452, and 3.411 to 3.503). No single configuration
wins both axes, so the default stays off and the trade is on record.

**5. A pre-existing defect was found and fixed en route: quantile crossing.** The
ordering invariant `lower <= point <= upper`, asserted in R2.1's property list and in
`formulation-uncertainty.md` §R2.1, is violated by the shipped CQR model, which fits three
*independent* quantile learners and conformalizes only the lower/upper pair. Measured:
**174 of 32,665** predictions out of order on real data at 365 days, and 10 of 30
synthetic seeds affected. The old `test_interval_ordering` passed on a single lucky
seed. `lower > upper` never occurred, so the interval always carried its guarantee and
**no coverage result is affected**; only the point forecast, which is the field the
scenario layer consumes. The point is now clipped into its interval, the count is
surfaced as `n_point_clipped` so the fix cannot mask a bad median model, and the test
is swept over the failing seeds. **Normalization eliminates the crossing entirely**
(174 to 0), which is an argument for it independent of accuracy.

**6. Out-of-season: normalization helps and is not enough.** Stale fit carried from
Feb-Jun into Nov-Dec: **cqr 0.788 to 0.820**, **split 0.817 to 0.831**, at roughly 38
percent more width. Both stay below the 0.85 floor, so open question 4 resolves to
"leave the pin untouched". Rolling recalibration (R2.1d) remains the effective
response to a season boundary; de-levelling recovers about a third of the gap.

## Golden oracles

The transform is exact arithmetic, so this phase has real oracles despite being a
forecasting change.

| # | inputs | expected | why this case |
|---|--------|----------|---------------|
| 1 | a price window with known mean 50 and standard deviation 10, `window_h=168`, `gap_h=24` | `level` = 50.0 and `scale` = 10.0 exactly at the first fully-warmed target | pins the baseline arithmetic and the warm-up boundary |
| 2 | a target whose baseline window ends at `t-24h`; mutate every price from `t-24h` onward | `level` and `scale` at `t` unchanged | the leakage gap, as an oracle rather than only a property |
| 3 | a flat price window (zero variance) | `scale` equals the floor, not zero; the inverse transform is finite | the division edge case that would otherwise produce infinities |
| 4 | standardized bounds `lo`, `hi` with known `level`, `scale` | inverted bounds equal `level + scale*lo` and `level + scale*hi` to floating-point exactness, and ordering is preserved | pins the affine inversion the coverage argument rests on |
| 5 | `normalize_target=False` on a fixed seed and input | point, lower and upper bit-identical to the R2.1d model | the opt-in identity, the anchor that cannot be faked for "nothing else moved" |

## Property tests

- **Opt-in identity:** with `normalize_target=False` and `season_encoding="month"`,
  the feature matrix and the forecast are byte-identical to R2.1d, for any drawn
  input.
- **No leakage, still:** features and baseline at `t` are invariant to mutation of
  any price at or after `t - 24 h`.
- **Coverage is transform-invariant:** on synthetic data, empirical coverage of the
  inverted interval equals coverage of the standardized interval exactly. This is
  the property that makes the inherited-guarantee argument testable rather than
  merely asserted.
- **Interval ordering survives inversion:** `lower <= point <= upper` in price
  space, including where `scale` hits its floor.
- **Scale is strictly positive** everywhere, for any input including constant and
  negative price series.
- **Width scales with recent volatility:** doubling the volatility of the trailing
  window, holding the level fixed, does not narrow the predicted interval. The
  non-vacuity check, since "coverage unchanged" alone cannot distinguish a working
  transform from an inert one.
- **Cyclical encoding is in range on a full-year window** and continuous across the
  December to January boundary, which is the defect `month` has and the reason the
  encoding is worth re-applying at all.

## Acceptance gate

*Blocks:* nothing downstream is queued; this closes the R2.1 line.

Statistical gates, in R2.1d's sense: decided on interval overlap, not on a point
estimate landing in a band.

Verified by re-running the live forecaster gate on 2026-07-28 (10 passed, NL and BE
2021-01-01 to 2025-09-30, 260 test days); the measured values are recorded beside
each box.

- [x] **Marginal coverage must not break.** Both methods, R2.1d's span and folds:
      the 95 percent day-block interval still overlaps `[0.85, 0.95]`.
      *Measured: raw 0.9003, normalized 0.9008; cqr interval [0.883, 0.916].*
- [x] **Conditional coverage is the headline, and it is reported honestly.**
      Maximum absolute deviation of hour-of-day coverage from nominal is reported
      against the recorded baseline. **Improve or tie**, in the null-tolerant style
      of R2.1c and R2.5: a measured null is a pass and is recorded as a finding,
      but a material worsening is a failure.
      *Measured: max hour deviation 0.0653 raw to 0.0498 normalized (cqr), a 24
      percent reduction. See Measured results finding 1 for why an earlier reading
      of this line called it a null.*
- [x] **Sharpness must not regress.** Pinball skill against seasonal naive stays
      below 1 at both edges and no worse than R2.1d's 0.219 / 0.280 by more than
      noise.
      *Measured: 0.219 / 0.280, unchanged; mean width 138.3 raw to 134.8
      normalized, so intervals are narrower rather than wider.*
- [x] **Opt-in identity holds**, pinned by oracle 5 and the identity property.
      *Both green in the full suite.*
- [x] **The training-window sweep under normalization is reported**, including if
      it fails to change the raw-target ordering.
      *Reported in [the target-normalization study](../studies/target-normalization.md);
      the ordering flips at 365 days.*
- [x] Reproducibility: fixed seed and inputs give bit-stable output.
      *Property test green.*
- [x] R1, R2.2, R2.3, R2.4, R2.5, R2.6 gates untouched.
      *Full suite 373 passed / 29 skipped.*

## Out of scope

- **Adaptive conformal for distribution shift (ACI)** and other online-update
  schemes. R2.1b's drift monitor plus rolling recalibration is the project's
  answer to shift, and R2.1d gated it.
- **Conditional coverage *guarantees*.** This phase improves conditional coverage
  empirically; it does not claim a conditional guarantee, which conformal
  prediction cannot give without further assumptions.
- **Hyperparameter tuning**, still. Unchanged reasoning from R2.1d.
- **Gas price, carbon price, or cross-border flow features.** The obvious next
  feature after residual load is a fuel price, and it is a new data-acquisition
  path in the R1.4b mould. Named as possible future work, not built here.
- **Re-running the R2.5, R2.5b and R2.6 value studies.** Still the right follow-up,
  still a different phase. Note that R2.1e cannot move those nulls anyway: the
  scenario layer reads only `forecast.point`, so interval quality does not reach
  the optimizer at all.
- **Deep-learning forecasters.** Out of scope since R2.1 and staying there.

## Decisions

All six resolved as proposed (2026-07-28, human's call). Proposals are kept above
their resolutions so the section stays a decision trail.

- **1. Baseline window: 168 h all-hours, or same-hour across 7 days?**
  **Resolved: 168 h all-hours.** *Proposed:* 168 h all-hours. Same-hour gives only 7 samples for the scale estimate, which is
  too noisy to divide by; the hour-of-day shape is what the model is supposed to
  learn, not what the baseline should absorb.
- **2. Should fundamentals be normalized too?** **Resolved: no, keep them in MW.**
  *Proposed:* no.
  They are bounded physical quantities without the price's level drift, and
  standardizing them would mix two unrelated scales for no measured reason. Revisit
  only if partial dependence shows the model failing on them.
- **3. Does `normalize_target` default to `True` once measured?**
  **Resolved: stays `False`, now on evidence rather than caution.** The measurement
  shows normalization helps at 365 days and above and *hurts* at 90 and 180, so it is
  not better everywhere, which is exactly the condition this question set for flipping
  a default. The recommended pairing is `normalize_target=True` with a 730-day
  training window, and that is documented rather than defaulted.
  *Proposed:* leave it `False` and decide after the measurement. Flipping a default is
  a claim that it is better everywhere, which the gate above does not establish if
  the result is a tie.
- **4. What happens to `test_coverage_gate_does_not_transfer_out_of_season`?**
  **Resolved: rewrite it to assert the improvement if coverage rises into the band,
  preserving the old numbers in its docstring; leave it untouched if it does not.**
  *Proposed:* if normalization lifts out-of-season coverage into the band, the test
  has done its job and is **rewritten to assert the improvement**, with the old
  numbers preserved in its docstring. Its own docstring already instructs exactly
  this ("that is good news and not a broken test"). It is not loosened, and it is
  not deleted. If coverage stays below the band, it is left untouched and the
  finding is that de-levelling did not fix the season boundary.
- **5. Governing reference.** **Resolved: ship ungoverned unless the citation
  verifies**, per the R2.1d precedent. *Proposed:* Lei, G'Sell, Rinaldo, Tibshirani and
  Wasserman, *Distribution-Free Predictive Inference for Regression* (JASA, 2018),
  for locally-weighted and normalized nonconformity scores, which is what the
  standardized target amounts to. **Named from memory and NOT verified.** Per
  CLAUDE.md §1 the volume, issue and section must be checked against a publisher
  listing before it is cited, and `docs/references.md` stays unwritten for this
  phase until then. The affine-inversion argument in "Design" is self-contained and
  depends on nothing from it.
- **6. Phase id.** **Resolved: R2.1e.** *Proposed:* R2.1e, closing the R2.1 line.
