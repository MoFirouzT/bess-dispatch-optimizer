# Spec R2.1d. Walk-forward evaluation honesty (fold placement, span, gate statistics)

**Status:** Implemented (gate green 2026-07-28; open questions resolved as proposed)
**Release:** R2  **Depends on:** R1.4a (walk-forward discipline), R1.4b (ENTSO-E loader + cache), R2.1 (the forecaster and its coverage gate), R2.1c (the fundamentals claim this phase re-measures)
**Phases:** R2.1d (2026-07-28)

## Objective

Rebuild the R2.1 walk-forward harness so its output is a statement about the
forecaster rather than about one fortnight, then re-state the R2.1 and R2.1c
claims under it. **No model change**: same features, same learner, same conformal
wrappers. This phase changes only what is measured, how folds are placed, and how
the gate decides pass or fail.

It is deliberately sequenced before any model work (R2.1e: target normalization,
rolling-stat features, cyclical encoding). The current harness cannot evaluate
those changes, because it can only see mid-May 2024. Build the instrument first.

## What is wrong today

Four findings, each verified against the code rather than argued from principle.

1. **The three folds are one contiguous test period.** `walk_forward_coverage`
   takes the last `n_folds * test_days` days of the series, so on the live
   window (2024-02-01 to 2024-06-01) the blocks are 2024-05-18 to 05-22,
   05-23 to 05-27, and 05-28 to 06-01. Three folds whose training sets differ by
   ten days, tested on three adjacent blocks inside one fortnight, are one
   evaluation reported three times. Every current R2.1 and R2.1c number
   (coverage 0.899, pinball delta of minus 16.6 percent) is a mid-May 2024
   statement about a single zone.
2. **The coverage tolerance is asserted, not derived, and cites the wrong
   quantity.** R2.1 resolved-decision 5 justifies the `0.9 ± 0.05` band by "the
   walk-forward calibration-set size". Coverage sampling noise is governed by the
   **test** set, and coverage indicators cluster within a day (one bad day misses
   roughly 24 in a row). At 15 effective test days the standard error is about
   0.077, so the band is narrower than the noise of the statistic it gates. This
   is the same category error already fixed once in this project, when the R2.5
   VSS gate replaced an exact threshold on a sampling statistic with a sign test.
3. **Coverage is gated; sharpness is not.** The only width check is
   `assert width > 0.0`. Coverage alone is satisfiable by predicting plus or
   minus infinity, so the gate as written cannot separate a good forecaster from
   a wide one. `walk_forward_pinball_skill` already exists in
   `bess.forecaster.evaluate` and is exercised only by the R2.1c test, never as
   an R2.1 gate.
4. **The gated model is not the shipped model.** `PriceForecaster` defaults to
   `n_estimators=200`; the coverage gate runs 60 and the fundamentals gate runs
   120. Three capacities, three different models, one claim.

A fifth item is spec drift rather than a measurement defect, and is listed under
build tasks: R2.1's scope section promises "lags, rolling stats, and calendar",
and `bess.forecaster.features` implements lags and calendar only.

## Formulation reference

**No optimizer delta.** No constraint, variable, objective term, or efficiency
placement changes; `docs/formulation.md` is untouched.

One canonical edit is required. [`formulation-uncertainty.md` §R2.1](../formulation-uncertainty.md#r21-probabilistic-price-forecast-conformal-intervals-no-optimizer-change)
states the gate as "empirical coverage under the R1.4 walk-forward must land in
`1 − α ± 0.05`". That sentence is replaced by the interval-based rule below, with
a changelog entry in the same change (CLAUDE.md §1). The coverage *guarantee* and
its exchangeability caveat are unchanged: this edits how the guarantee is tested,
not what it claims.

## Data window

| Item | Value | Why |
| --- | --- | --- |
| Zone | NL (primary), BE (generality check) | NL is the existing study zone; BE is already fetched and cached by the R1.4c guard test |
| Evaluation span | 2021-01-01 to 2025-09-30 | Covers calm 2021 H1, the gas-crisis onset and peak, the 2023 normalization, and the current high-solar regime |
| Upper bound reason | The SDAC market time unit moved to 15 minutes ([day-ahead is 15-minute native](../decisions/day-ahead-15min-native.md)) | `validate_utc_index` requires a single regular frequency, so a window crossing the switchover raises rather than silently mis-lagging. Handling mixed resolution is out of scope here |
| Verified size | 41,593 hourly points, 1734 days, one regular hourly step | Measured by build task 0, not estimated |

**Build task 0 findings (probed live 2026-07-28, NL).** Recorded here because the
phase is designed against them rather than against an assumption.

- **The exact switchover is 2025-10-01 00:00 local time**, that is 2025-09-30
  22:00 UTC; the first 15-minute step in the raw feed is at 2025-10-01 00:15
  local. The chosen upper bound sits safely below it, and the whole span fetches
  as a **single regular hourly series** (verified end to end through the loader,
  not inferred). A window that does cross the switch fails loudly in
  `validate_utc_index` with "gaps / irregular freq", so there is no silent
  mis-lagging failure mode to defend against.
- **The fundamentals endpoints reach back to 2021-01.** Both the load forecast and
  the wind/solar forecast return data for 2021, 2022, and 2023 on the same hourly
  UTC grid the loader normalizes to, so the R2.1c claim can be re-measured across
  the whole span rather than only on 2024.
- **The span really does contain distinct regimes**, which is the point of
  choosing it. NL yearly mean and standard deviation in EUR/MWh: 2021
  **102.97 / 74.71**, 2022 **241.88 / 131.57** (the crisis), 2023 **95.81 /
  49.06**, 2024 **77.28 / 49.49**, 2025 through September **86.34**. Roughly a
  3x spread in level across the span, against the 4-month window whose whole
  range the current gate lives inside.
- **Negative prices are now routine and are growing**: share of hours below zero
  runs 0.8 percent (2021), 1.0 (2022), 3.6 (2023), 5.2 (2024), with a minimum of
  minus 500 EUR/MWh in 2023. This is a binding constraint on R2.1e: any
  de-levelling of the target must be **additive**, never a log or a ratio.

The gas-crisis period enters this phase as **held-out evaluation only**. Whether
it is usable as *training* data is a question about target parameterization, not
about data volume, and it belongs to R2.1e: under the raw price target a crisis
window drags the level and inflates intervals for calm regimes, while under a
de-levelled target it contributes transferable shape and volatility structure.
That contrast is the discriminating test for R2.1e's central change, so this
phase must not pre-empt it.

## Parameters / configuration

| Item | Where | Default | Change from R2.1 |
| --- | --- | --- | --- |
| fold placement | evaluate harness | evenly spaced across the span | was: contiguous, at the end |
| `n_folds` | evaluate harness | 52 | was 3 |
| `test_days` | evaluate harness | 5 | unchanged |
| training window | evaluate harness | rolling, fixed length | was expanding (all history before the block) |
| `train_days` | evaluate harness | 365 | was implicit (whatever preceded the block) |
| gate rule | integration gate | day-block bootstrap CI vs the tolerance band | was a point estimate in `[0.85, 0.95]` |
| bootstrap resamples | integration gate | 2000, fixed seed | new |
| CI level | integration gate | 0.95 | new |
| `n_estimators` | every gate | 200 (the shipped default) | was 60 / 120 / 200 |

**Why rolling rather than expanding.** Over a 4.7-year span an expanding window
makes the first fold train on months and the last on years, so training length is
confounded with date and no two folds are comparable. A fixed-length rolling
window makes every fold a like-for-like measurement and matches how the model
would actually be operated: retrained on a trailing window, not on all history.
It also promotes "how much history?" from an argument to a swept parameter.

**Why 52 folds of 5 days.** 260 test days at roughly one fold per fortnight
across the span. Treating the day as the effective sample unit (the project's own
reading in `docs/STATE.md`), the standard error of pooled coverage falls to about
0.019, so a 5-point tolerance band is roughly 2.7 standard errors and is
defensible for the first time. Cost is about 52 fits times 3 quantile models per
configuration, seconds each on a 365-day training window, so roughly a minute per
configuration and a few minutes for the full gate.

**`train_days = 365` is a default, not a finding.** It is the shortest window
containing every season exactly once, which is the mechanism that would remove
the month-extrapolation failure pinned by
`test_coverage_gate_does_not_transfer_out_of_season`, and it is the minimum for a
cyclical calendar encoding to be valid at all. Whether it beats 730 is measured,
not assumed, by the sweep below.

## Interfaces

All additions live in `bess.forecaster.evaluate`. No new module, no layering
change, no new dependency.

```python
@dataclass(frozen=True)
class Fold:
    """One walk-forward fold: a training day range and a strictly later test block."""
    train_start: pd.Timestamp
    train_end: pd.Timestamp    # exclusive; < test_start (the no-leakage invariant)
    test_start: pd.Timestamp
    test_end: pd.Timestamp     # inclusive


def rolling_origin_folds(
    days: pd.DatetimeIndex, *, n_folds: int, test_days: int,
    train_days: int | None = None, spacing: str = "even",
) -> list[Fold]:
    """Folds across the span. `train_days=None` keeps the R2.1 expanding window,
    an int gives a fixed-length rolling one. `spacing="contiguous"` reproduces the
    R2.1 blocks (tiling the end of the series); `"even"` spreads folds across the
    whole span. Raises if the span cannot host the request."""


@dataclass(frozen=True)
class CoverageResult:
    """Pooled coverage with its day-block bootstrap interval and sharpness."""
    coverage: float
    ci_low: float
    ci_high: float
    mean_width: float
    n_test_days: int
    per_fold: tuple[float, ...]


def coverage_ci(covered_by_day: Sequence[np.ndarray], *, level: float, n_boot: int,
                seed: int) -> tuple[float, float]:
    """Day-block (nonoverlapping) bootstrap CI for pooled coverage. Resamples whole
    days, so intra-day dependence in the coverage indicator is preserved."""
```

`walk_forward_coverage` gains `n_folds`, `test_days`, `train_days`, and a
`return_detail` flag, returning `CoverageResult` when set and the existing
`(coverage, width)` tuple otherwise. `walk_forward_pinball_skill` takes the same
fold parameters and shares the fold list. **The R2.1 defaults are preserved
exactly** (`n_folds=3`, `test_days=5`, `train_days=None`, contiguous placement at
the end of the series), so the historical number stays reproducible and is pinned
by a property test rather than by memory.

## Build tasks

- [x] **Build task 0 (repo guardrail, before any code):** probe the live feed and
      print real samples, rather than coding against an assumed schema or
      availability date (CLAUDE.md §7). Done 2026-07-28; results recorded under
      "Data window" above. The upper bound and the fundamentals reach-back were
      both confirmed by fetch, and the regime and negative-price statistics that
      motivate R2.1e were measured in the same pass.
- [x] `rolling_origin_folds` plus `Fold`; pure pandas, no forecaster import, so
      the fold-placement oracles run without the `forecast` dependency group.
- [x] `coverage_ci` (day-block bootstrap, fixed seed, deterministic).
- [x] Rewire `walk_forward_coverage` and `walk_forward_pinball_skill` onto the
      shared fold list; add `CoverageResult`; preserve the R2.1 default path.
- [x] Unify `n_estimators` at the shipped default across every gate that fits a
      forecaster, and delete the per-test `_FAST` overrides.
- [x] Add the sharpness axis to the R2.1 gate: walk-forward pinball skill against
      the seasonal-naive baseline, on the same folds as coverage.
- [x] Add a rolling-recalibration gate: fit once, then roll `recalibrate` on a
      trailing window across the span, and measure coverage under the operating
      procedure `bess.forecaster.drift` actually prescribes. The stale-fit case
      stays pinned as it is.
- [x] Re-measure and restate: R2.1 coverage (both methods), R2.1c fundamentals
      delta, the out-of-season claim, each with its CI, on the new span. Update
      the R2.1 and R2.1c specs, `formulation-uncertainty.md` §R2.1, and `docs/STATE.md` to
      whatever the measurement says.
- [x] Training-window sweep at 90 / 180 / 365 / 730 days, reported with CIs;
      outcome recorded under "Measured results" below. Scratchpad study, and only
      the chosen default is committed.
- [x] Resolve the rolling-stats spec drift: either implement them (then they are
      R2.1e, a model change) or amend R2.1's scope line to match the code. This
      phase does the amendment; it does not add features.
- [x] `ruff` / `format` / `mypy` / `lint-imports` / `lint_docs` clean; every R1
      and R2 gate outside R2.1 unchanged.

## Golden oracles

Fold placement is exact arithmetic, so unlike the rest of forecasting this phase
does have un-fakeable oracles.

| # | inputs | expected | why this case |
|---|--------|----------|---------------|
| 1 | 100 days, `n_folds=3`, `test_days=5`, `train_days=None` | the R2.1 blocks: days 85 to 89, 90 to 94, 95 to 99 | pins backward compatibility as arithmetic, so the historical R2.1 number stays reproducible |
| 2 | 1000 days, `n_folds=10`, `test_days=5`, `train_days=365` | first test block starts at day 365; blocks evenly spaced; last block ends at day 999 | pins even spacing and the rolling-window start |
| 3 | 400 days, `n_folds=52`, `test_days=5`, `train_days=365` | raises: the span cannot host 52 non-overlapping blocks after a 365-day warm-up | pins the loud failure instead of silently overlapping folds |
| 4 | every fold of case 2 | `train_end < test_start`, and each training range spans exactly 365 days | the no-leakage and fixed-length invariants, as an oracle rather than a property |
| 5 | a hand-built day sequence with coverage exactly 0.5 on 100 days, `n_boot=2000`, seed 0 | point estimate exactly 0.5; CI brackets it; CI width matches the analytic binomial standard error to two decimals | pins the bootstrap against a case with a known answer |

## Property tests

- **No leakage, every fold:** `train_end < test_start`, for every generated fold,
  over Hypothesis-drawn spans and fold parameters.
- **Folds are disjoint, ordered, and equal length:** test blocks never overlap,
  are strictly increasing, and each spans exactly `test_days`.
- **Fixed training length:** with `train_days` set, every fold trains on exactly
  that many days, or the generator raises. Never a short fold in silence.
- **Backward compatibility:** with the R2.1 defaults, the fold list equals the
  blocks the current implementation produces, for any span it accepts.
- **Bootstrap CI is well formed:** `ci_low <= coverage <= ci_high`, the interval
  is deterministic under a fixed seed, and its width decreases as the number of
  test days grows.
- **Coverage estimator is unbiased on exchangeable synthetic data:** on the R2.1
  synthetic series, pooled coverage stays within the CI of nominal across
  Hypothesis-seeded noise draws.
- **Day-block resampling actually blocks:** on a constructed series whose
  coverage indicator is perfectly correlated within each day, the block bootstrap
  CI is strictly wider than a naive per-observation bootstrap CI. Without this,
  a resampler that silently ignored the blocking would pass everything else.

## Acceptance gate

*Blocks:* R2.1e. Every box must pass.

These remain **statistical** gates, in R2.1's sense. What this phase changes is
that the decision rule now accounts for the sampling noise of the statistic it
tests, instead of comparing a noisy point estimate to a fixed band.

- [x] **Coverage (headline, restated).** On the full span, both methods: the
      95 percent day-block bootstrap CI for pooled coverage **overlaps**
      `[0.85, 0.95]`. The gate fails only when the whole interval lies outside
      the band, that is, when the data can rule out the tolerance claim. This
      strengthens as data grows, since a narrower CI is harder to overlap when
      coverage is genuinely off, which is the right direction and matches the
      project's rule that a red gate means the code is wrong.
- [x] **Sharpness (new axis).** Walk-forward pinball skill against seasonal naive
      is below 1 at both interval edges, on the same folds. A forecaster that
      buys coverage with width fails here.
- [x] **Reproducibility.** Fixed seed and fixed inputs give bit-stable folds,
      coverage, and CI bounds.
- [x] **One model.** Every gate that fits a forecaster uses the shipped default
      capacity; no per-test override remains.
- [x] **Restated claims.** The R2.1 coverage claim, the R2.1c fundamentals delta,
      and the out-of-season finding are each reported with a CI and a named span,
      and the specs and `docs/STATE.md` say what was measured. **A result that
      contradicts a current claim is recorded as the finding, not suppressed**;
      in particular the R2.1c pinball gain may shrink or vanish once it is
      measured across seasons rather than in one fortnight, and that outcome is
      an acceptable pass for this phase.
- [x] R1, R2.2, R2.3, R2.4, R2.5, R2.6 gates untouched.

## Measured results (2026-07-28)

**The R2.1 coverage claim survives the harder test, and is now actually justified.**
NL 2021 to 2025, 260 evaluated days, shipped model capacity: **cqr 0.900**, 95% CI
[0.883, 0.916], mean width 138.3 EUR/MWh; **split 0.892**, CI [0.874, 0.909], width
160.3. BE, same configuration: **0.903**, CI [0.886, 0.920]. The claim now rests on
4.7 years, two zones and a gas crisis rather than on one fortnight of May 2024. That
it did not move is the expected outcome for a reason worth stating: conformal
marginal coverage is self-calibrating, and a rolling window keeps each fold's
calibration split adjacent to its test block, so coverage holds across regimes even
where accuracy does not.

**The interesting failure is conditional, not marginal.** Per-fold coverage ranges
**0.617 to 1.000** (cqr) and 0.575 to 1.000 (split). Pooled coverage is essentially
exact while individual folds are badly miscalibrated in both directions. §R2.1
already lists conditional coverage under "considered but out of scope"; this measures
what that costs instead of asserting it, and it is the strongest argument for R2.1e.

**Sharpness, the axis that did not previously exist.** Walk-forward pinball at the
interval edges, cqr: conformal **4.999 / 4.541** against seasonal-naive **22.845 /
16.219**, so skill **0.219 / 0.280**. The intervals are roughly four times sharper
than the baseline, which is what makes the coverage number worth anything.

**The R2.1c fundamentals gain shrinks but holds.** Re-measured on 260 days across
the span at shipped capacity: pinball **minus 13.4 percent** (4.770 to 4.132) with
coverage preserved (0.894, CI [0.876, 0.912]). The originally reported minus 16.6
percent was a 15-day, 120-tree number; the effect was somewhat inflated by its
window, and it is real.

**Rolling recalibration works, and is now gated.** Base learners frozen at the June
fit, conformal quantile refreshed on a trailing 28-day window, rolled across 34
winter days: **cqr 0.757 to 0.870**, **split 0.791 to 0.890**, paid for in width
(98.9 to 184.9, and 102.3 to 152.4). The stale-fit pin is unchanged at **0.788 /
0.816** out of season.

**Training-window sweep, and the first answer was wrong.** Run naively, one row per
window length with folds placed wherever each length allows, the result looked like
"longer is better": coverage 0.843 / 0.855 / 0.900 / 0.891 and pinball 5.295 / 5.250
/ 4.770 / 3.711 at 90 / 180 / 365 / 730 days. **That comparison is confounded**, and
by exactly the defect this phase exists to remove: a fold cannot start before its
training window is full, so each row was scored on a *different* test period, and
only the short-window rows were tested on the hard 2021 to 2022 crisis.

Re-run with every row scored on **identical** test days (2023-01-01 to 2025-09-30,
achieved by sliding each series start so the first fold lands on one date), the
conclusion reverses:

| `train_days` | coverage | 95% CI | mean width | pinball |
| --- | --- | --- | --- | --- |
| 90 | 0.887 | [0.866, 0.905] | 96.8 | 3.574 |
| 180 | 0.896 | [0.876, 0.913] | 100.6 | 3.674 |
| 365 | 0.916 | [0.900, 0.931] | 107.0 | 3.532 |
| 730 | 0.891 | [0.870, 0.909] | 106.0 | 3.711 |

**Accuracy is flat in the training window** (pinball spans 3.53 to 3.71, about 5
percent, with 365 best and 730 worst), coverage is acceptable at every length, and
width *grows* with window length. So there is no measured accuracy case for a longer
window on this data, and none at all for two years.

**Resolved: `train_days = 365` stays the default, on the seasonal-representation
argument rather than on a measured accuracy edge.** It gives the best coverage and
the best pinball of the four, but by margins inside the noise; the honest reasons to
prefer it are that it contains every season exactly once and that it is the
precondition for the cyclical encoding R2.1e re-tries. **Two years is not worth its
1.5x runtime**, which also settles, for the raw-target model, whether gas-crisis
history helps as *training* data: it does not. Whether it helps a de-levelled target
is the R2.1e question and is deliberately still open.

## Out of scope

- **Any model change.** Target normalization, rolling-stat features, the cyclical
  calendar encoding, and the training-window default that the sweep recommends
  are R2.1e. This phase measures; it does not improve.
- **15-minute resolution handling.** The span stops at the switchover. Supporting
  a mixed-resolution series is its own phase and touches the R1.4b loader, the
  R1.4c guard, and `dt` handling throughout.
- **Re-running the R2.5, R2.5b, and R2.6 value studies on new windows.** The same
  single-window criticism applies to all three, and every headline null in
  Release 2 rests on NL over four months of 2024. It is the right follow-up and
  is named here, but it is a study-harness phase, not this one.
- **Hyperparameter tuning.** Lowest expected payoff of the available changes, and
  tuning on any single window risks fitting that window.
- **Cross-conformal or jackknife-plus.** Worth reconsidering only if the training
  window stays short; a 365-day window and a 30 percent calibration split gives
  ample calibration points, so it and a wider window are substitutes.
- **Additional zones beyond the BE generality check**, and cross-border joint
  forecasting (already out of scope in R2.1).

## Decisions

All six resolved as proposed (2026-07-28, human's call). The proposals are kept
above their resolutions so the section stays a decision trail.

- **1. Gate rule: CI overlap with the tolerance band, or CI containing nominal?**
  **Resolved: CI overlap with `[0.85, 0.95]`.** *Proposed:* overlap. Requiring the CI to contain 0.9
  exactly becomes unsatisfiable as the test set grows, since any real
  miscalibration of a fraction of a point would eventually fail; the overlap rule
  tests the claim the project actually makes, which is that coverage is within 5
  points of nominal.
- **2. Fold spacing: evenly spaced, or contiguous blocks tiling the span?**
  **Resolved: evenly spaced**, with contiguous kept as the R2.1 compatibility
  path. *Proposed:* evenly spaced. Tiling the whole span gives about 273 folds and 4 to
  5 times the runtime for a standard-error improvement of roughly 2 times, and
  even spacing samples seasons more uniformly at a given fold count.
- **3. Does BE run the full gate, or a reduced generality check?**
  **Resolved: reduced.** *Proposed:* reduced. BE runs coverage and sharpness at the default configuration only; the
  sweep and the recalibration gate stay NL-only, to keep the live tier inside a
  few minutes.
- **4. Does the out-of-season test survive this phase?** **Resolved: yes,
  unchanged**, with the new recalibration gate beside it. *Proposed:* yes. It pins a stale fit across a season boundary, which stays true and
  stays worth pinning. The new recalibration gate sits next to it and measures
  the mitigation, so the pair states the limitation and its documented response.
- **5. Governing reference.** **Resolved: ship ungoverned unless the citation
  verifies**, following the R2.1b / R2.2b precedent; the block bootstrap and the
  fold arithmetic are standard and self-contained, so nothing here depends on it.
  *Proposed:* Lago, Marcjasz, De Schutter and Weron,
  *Forecasting day-ahead electricity prices: a review of state-of-the-art
  algorithms, best practices and an open-access benchmark* (Applied Energy,
  2021), for walk-forward evaluation protocol and calibration-window choice.
  **Named from memory and therefore NOT verified.** Per CLAUDE.md §1 the edition,
  volume, and section must be checked against a publisher listing before it is
  cited, and `docs/references.md` stays unwritten for this phase until then. The
  phase relies on nothing from it: the block bootstrap and the fold arithmetic
  are standard and self-contained.
- **6. Phase id.** **Resolved: R2.1d.** *Proposed:* R2.1d, continuing the R2.1 / R2.1b / R2.1c line,
  with the model changes as R2.1e.
