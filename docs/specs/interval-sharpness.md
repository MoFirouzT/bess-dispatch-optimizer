# Spec R2.1f: Interval sharpness at fixed coverage

**Status:** Implemented (2026-08-31). The gate returned **no adoption**: two boxes
ran and did not pass, `max_hour_deviation` on NL (0.070 against 0.065) and pinball skill
at BE's lower edge (0.196 against 0.192). Nothing in `src/bess/forecaster/forecast.py`
changed.
**Release:** R2  **Depends on:** R2.1 (the forecaster and its conformal wrappers), R2.1d (the fold layout and the gate statistics), R2.1e (the feature and target settings this phase holds fixed), R2.8 (the seed-width discipline)
**Phases:** R2.1f

## Objective

Search the quantile learners' hyperparameters for the narrowest conformal interval
that keeps coverage on target, select on delivery days no reporting gate ever scores,
and state the width change with its uncertainty.

*Assumes:* the conformal construction in
[formulation-uncertainty.md § R2.1](../formulation-uncertainty.md#r21-probabilistic-price-forecast-conformal-intervals-no-optimizer-change);
the fold layout and gate statistics in [R2.1d](forecaster-evaluation.md);
the seed-width rule in [R2.8](draw-noise.md).

## Motivation

The shipped forecaster runs LightGBM at `n_estimators=200` and library defaults
everywhere else.
Those numbers were never chosen against an objective.
R2.1d found and fixed the fact that three different capacities were gated as one claim,
and fixed the capacity at the shipped 200, but fixing a number is not choosing it.

Conformal calibration makes this a search over **width alone**.
Whatever the quantile models do, the conformal step moves the bounds until marginal
coverage lands near $1-\alpha$, so a worse base model is not an uncovered interval,
it is a wider one.
The quantity hyperparameters actually move is therefore sharpness, and sharpness is
the half of the R2.1 claim that has never been optimized, only gated.

**Why this and not a better learner.**
[forecast-value](../studies/forecast-value.md) measured whether forecast accuracy
converts into dispatch euros and found nothing:
a median of $-6.20$ EUR per window on NL and $-11.67$ on BE against a seasonal-naive
forecast, despite pinball loss running $0.22\times / 0.28\times$ the naive baseline.
Point accuracy past the naive baseline is already known not to pay.
Interval *width* is a different input: the R2.2 scenario set is drawn from the interval,
so width sets the spread of the paths R2.3 optimizes over, and the dispatch is a
function of that spread in a way it is not a function of the median.
This phase measures the width move; whether it pays is a euro question and is stated
as a gate below rather than assumed.

**A null is a result.**
If no configuration beats the incumbent by more than seed noise, the phase reports
that and the shipped defaults do not change.

## Formulation reference

[`formulation-uncertainty.md` § R2.1](../formulation-uncertainty.md#r21-probabilistic-price-forecast-conformal-intervals-no-optimizer-change).

**No optimizer delta.** No constraint, variable, objective term, or efficiency
placement changes; `docs/formulation.md` is untouched.

**One canonical edit, in the same change** (CLAUDE.md §1).
§R2.1 currently names sharpness only as a companion gate ("coverage is gated alongside
sharpness").
It gains the selection rule below, because a phase that *chooses* a model on sharpness
turns sharpness from a check into part of the definition of the shipped forecaster.

## Governing reference

**None required.**
Grid search over hyperparameters against a held-out objective is textbook-ubiquitous.
The conformal construction being searched over is already governed by the R2.1
reference (Angelopoulos & Bates).

## Design sketch

Let $C$ be a candidate configuration and $F_{\text{tune}}$ the tuning folds.
Write $\bar w(C)$ for mean interval width pooled over the tuning test blocks,
$\hat c(C)$ for pooled coverage, and $\delta_h(C)$ for the largest deviation of
per-hour coverage from nominal (`CoverageResult.max_hour_deviation`).

Select

$$C^\star = \arg\min_{C \in \mathcal{C}} \bar w(C)
\quad \text{s.t.} \quad \hat c(C) \in [0.85, 0.95],
\quad \delta_h(C) \le \delta_h(C_0),$$

ties broken by median width, then by the cheaper model (fewer trees, then fewer
leaves), then by a canonical ordering of the parameters.
Every tie-break is a property of the candidate rather than of where it sat in the grid,
so permuting the grid cannot change the answer.
An index-based tie-break was written first and a property test rejected it: two
configurations can score identically to the last bit, and the winner then depended on
the order the grid happened to be written in.

$C_0$ is the incumbent (the shipped defaults) and is always a candidate, so the search
cannot return something worse than what ships.

**The hourly-coverage constraint is the one doing real work.**
Mean width is minimized by an interval that is tight overnight and too tight at the
evening peak, which is marginally calibrated and conditionally wrong.
That is the failure the CQR decision record
([cqr-over-split-conformal](../decisions/cqr-over-split-conformal.md)) exists to avoid,
and it is exactly the shape the dispatch layer trades on.
So sharpness is bought only where it does not cost conditional calibration.

### Fold disjointness

The reporting layout is R2.1d's, unchanged: `n_folds=52, test_days=5, train_days=365,
spacing="even"` over the 2021-01-01 to 2025-09-30 span, whose test blocks run
**2022-01-01 to 2025-09-30** (verified against `rolling_origin_folds`).
All of 2021 is training-only and is scored by no gate.

The tuning blocks are placed in the **gaps between the reporting blocks**: 12 blocks
of 5 days, each centred in a clear gap, with the same 365-day training window as a
reporting fold.
The reporting layout leaves about 22 clear days between consecutive blocks, so a tuning
block sits in the middle of a gap without touching either neighbour.

No tuning test block is a reporting test block, so the reported width is not the
width the winner was selected on.
A tuning fold's *training* window does overlap reporting test days, which is not
leakage: the discipline is that a fold never trains on data at or after its own test
block, and every reporting block stays unseen by the selection.

**This replaces the 2021 placement this spec was approved with, which implementation
killed.**
Measured 2026-08-31 on NL at an identical 12-fold, 180-training-day placement, pooled
coverage runs **0.791 in 2021, 0.847 in 2022, 0.887 in 2023 and 0.897 in 2024**, against
monthly NL means climbing 77 to 238 EUR/MWh across 2021 H2.
Conformal coverage assumes exchangeability and a hard upward trend in the level breaks
it, so 2021 is the worst-calibrated stretch in the span: the *incumbent* misses the
coverage band there, no candidate is feasible, and the search raises rather than
returning a winner.
Selecting a model on the one regime where the method is out of calibration would also
have meant optimizing width against a coverage failure.
The gap placement keeps the disjointness that made 2021 attractive and drops the regime
mismatch the spec had accepted as a known weakness.

## Parameters / configuration

The grid, frozen in a new `tune.py` under `bess.forecaster`:

| Knob | Values | Incumbent |
| --- | --- | --- |
| `n_estimators` | 100, 200, 400, 800 | 200 |
| `learning_rate` | 0.03, 0.05, 0.1 | 0.1 |
| `num_leaves` | 15, 31, 63 | 31 |
| `min_child_samples` | 20, 50, 100 | 20 |
| `calib_fraction` | 0.2, 0.3, 0.4 | 0.3 |

324 configurations.
A full 52-fold CQR evaluation on the cached NL span takes **20.6 s** (measured
2026-08-31, `random_state=0`, coverage 0.9003, mean width 138.35 EUR/MWh), so the
12-fold tuning evaluation is roughly a quarter of that and the exhaustive grid runs in
well under an hour.
The grid is enumerated in full; no random search, so the result does not depend on a
search seed.

`calib_fraction` is in the grid because it moves width directly: it sets how many
points the conformal quantile is estimated from, and a short calibration block buys a
noisier and typically wider correction.

Everything else is held at its shipped R2.1e value:
features, lags, `season_encoding`, `rolling_stats`, `normalize_target`,
`confidence_level=0.9`, `method="cqr"`.

## Interfaces

```python
@dataclass(frozen=True)
class SharpnessCandidate:
    params: Mapping[str, object]     # the LightGBM + calib_fraction overrides
    coverage: float
    mean_width: float
    median_width: float
    max_hour_deviation: float
    feasible: bool                   # met both constraints
    reason: str                      # why infeasible, "" when feasible


@dataclass(frozen=True)
class SharpnessSearch:
    incumbent: SharpnessCandidate
    selected: SharpnessCandidate
    ranked: tuple[SharpnessCandidate, ...]   # feasible only, sharpest first
    all_candidates: tuple[SharpnessCandidate, ...]   # grid order, infeasible included


def search_sharpest(
    prices: pd.Series,
    *,
    grid: Sequence[Mapping[str, object]] | None = None,   # None -> the frozen grid
    fundamentals: pd.DataFrame | None = None,
    coverage_band: tuple[float, float] = (0.85, 0.95),
    n_folds: int = 12,
    test_days: int = 5,
    train_days: int = 180,
    spacing: str = "even",
    random_state: int = 0,
) -> SharpnessSearch: ...
```

`median_width` is added to `CoverageResult` in the same change; mean width alone is
dominated by scarcity hours, and a tie-break needs the robust one.

## Layering (import-linter)

The new `tune.py` imports `bess.forecaster.evaluate` only.
`walk_forward_coverage` gains a `folds=` argument, since a gap placement is not a shape
`rolling_origin_folds` can express; passing `None` keeps every existing caller
byte-identical.
Intra-package, no contract touched; the expected KEPT count stays **5**.

## Build tasks

- [x] `median_width` on `CoverageResult`, populated by `walk_forward_coverage`
- [x] `tune.py` under `bess.forecaster`: the frozen grid, `search_sharpest`, the two constraints, deterministic tie-breaking
- [x] Export from `bess.forecaster.__init__` behind the existing lazy `forecast`-group import
- [x] Golden + property tests below, failing first
- [x] Live gate module `tests/integration/test_sharpness_live.py`, marked `studies` (it is a sweep, not a routine live check)
- [x] Run the search on NL and BE; record the selected configuration and both widths under Measured results
- [!] Adoption, only if the gate's width condition is met: change the `PriceForecaster` defaults, re-run the R2.1/R2.1d gates, and record the new incumbent numbers: **the condition was not met, so no default changed**
- [x] `formulation-uncertainty.md` §R2.1 selection-rule edit
- [x] Ledger row in [specs/README.md](README.md); `STATE.md` refresh

## Golden oracles

| # | inputs | expected result | why this case |
| --- | --- | --- | --- |
| 1 | synthetic seasonal prices, fixed 3-config grid, seed 0 | recorded ranking and selected params, bitwise | pins the whole search, not just the winner |
| 2 | grid where the narrowest config's coverage is 0.80 | that config excluded; runner-up selected | the coverage constraint binds, and binds against the *sharpest* candidate |
| 3 | grid where the narrowest config has worse `max_hour_deviation` than the incumbent | that config excluded | the conditional-calibration constraint binds |
| 4 | grid whose only feasible member is the incumbent | `selected == incumbent` | the null path returns the shipped model, not an error |

## Property tests

- Every returned `selected` has `coverage` inside the band and `max_hour_deviation` no worse than the incumbent's.
- `selected.mean_width <= incumbent.mean_width` always, since the incumbent is a candidate.
- Permuting the grid order leaves `selected.params` unchanged (deterministic tie-break).
- Re-running `search_sharpest` with the same seed and grid reproduces `ranked` bitwise.
- `ranked` is sorted by `mean_width` ascending and contains exactly the feasible candidates.
- No tuning fold's test block intersects any reporting fold's test block, for the two layouts named above.

## Acceptance gate

*Blocks:* adoption of new `PriceForecaster` defaults, and any later phase that
consumes interval width. Every box must pass.

- [x] The search runs to completion on the NL span and reproduces bitwise on a second run (same seed, same grid): 324 configurations, both zones; reproduction gated by `test_the_search_reproduces_bitwise_on_a_second_run`
- [x] No tuning test block intersects a reporting test block (asserted, not asserted-by-inspection): `test_no_tuning_test_block_intersects_a_reporting_test_block`
- [x] The selected configuration's coverage interval on the **reporting** folds still overlaps `[0.85, 0.95]`: NL [0.878, 0.913], BE [0.882, 0.918]
- [!] Its `max_hour_deviation` on the reporting folds is no worse than the incumbent's: **NL fails, 0.070 against 0.065**; BE passes, 0.054 against 0.058
- [!] Its pinball skill against seasonal naive is no worse than the incumbent's: NL passes, 0.213 / 0.266 against 0.219 / 0.280; **BE fails at the lower edge, 0.196 against 0.192**
- [x] The reporting-fold width change is stated with **both** widths: the day-block bootstrap interval over test days, and the spread over `random_state` in {0, 1, 2}. Per R2.8 the two are independent and are never combined: NL +6.22 [+3.17, +9.35], BE +2.87 [+0.02, +5.68]; the seed spread is 0.00 in both zones and is **structurally** zero, not a stability result (see Measured results)
- [x] The result is recorded whether or not it is an improvement: Measured results above

**Two boxes carry `- [!]`: they ran and did not pass.** That is the gate doing its
job, since it blocks adoption and adoption is what the measurement argues against.
Ticking them would require either weakening the constraints or reading the numbers
charitably, and the phase's finding is exactly that a real 4.5% width reduction is not
worth what it costs at 11:00. The marker itself is new, added to `scripts/lint_docs.py`
in this change: the rule previously admitted only "passed" and "no record", so a phase
whose honest outcome was "the gate says no" could not be marked Implemented without
fudging a tick.

**Adoption is conditional, not automatic.** The defaults change only if the width
reduction on the reporting folds exceeds the seed spread, on both NL and BE.
If it does not, the finding is that the shipped defaults were already at the useful
optimum, and nothing in `src/` changes.
**Outcome: not adopted.** Nothing in `src/bess/forecaster/forecast.py` changed; the
phase added the search and its measurement, and the shipped model is untouched.

**The euro re-run did not happen, because the defaults did not change.** Had they, it
would have run before the phase closed:
VSS at 10 seeds (about 25 min per STATE.md's budget) on NL and BE, reported against
R2.8's known 4.85 EUR seed spread. A sharper interval that moves no euros is still a
reportable result, and is the outcome [forecast-value](../studies/forecast-value.md)
predicts.

## Measured results

Run 2026-08-31, 324 configurations per zone, gap-placed tuning folds, reporting on
R2.1d's 52-fold layout over 260 delivery days.

**Verdict: no adoption. The shipped defaults stand.**

| | NL incumbent | NL selected | BE incumbent | BE selected |
| --- | --- | --- | --- | --- |
| mean width | 138.35 | **132.15** | 135.85 | **132.99** |
| coverage | 0.900 | 0.896 | 0.903 | 0.901 |
| coverage 95% CI | [0.883, 0.916] | [0.878, 0.913] | [0.886, 0.920] | [0.882, 0.918] |
| `max_hour_deviation` | 0.065 | 0.070 | 0.058 | 0.054 |
| pinball skill lower / upper | 0.219 / 0.280 | 0.213 / 0.266 | 0.192 / 0.268 | 0.196 / 0.264 |

Selected on NL: `n_estimators=400, learning_rate=0.03, num_leaves=15,
min_child_samples=50, calib_fraction=0.2`, 62 of 325 candidates feasible.
Selected on BE: `n_estimators=200, learning_rate=0.1, num_leaves=15,
min_child_samples=20, calib_fraction=0.2`, 301 of 325 feasible.

Width reduction with its day-block bootstrap interval over the 260 test days:
**NL +6.22 EUR/MWh, 95% CI [+3.17, +9.35], 57.3% of days narrower**;
**BE +2.87, 95% CI [+0.02, +5.68], 55.4% of days narrower**.

**Why adoption is blocked**, in the order the gate reaches it.

1. **NL fails the per-hour constraint**: 0.065 against the incumbent's, rising to 0.070.
   The two deviations are not the same failure. The incumbent's worst hour is **21:00 at
   0.965**, over-covering, so its interval is wastefully wide at the evening peak. The
   selected model's worst hour is **11:00 at 0.830**, under-covering, and hours 10 to 12
   move 0.861 / 0.857 / 0.849 to 0.842 / 0.830 / 0.861. The sharper model is narrower
   everywhere: that fixes the evening waste and pushes midday into real undercoverage.
2. **BE passes that constraint but fails the pinball box**: skill at the lower edge
   moves 0.192 to 0.196, which is worse, while the upper edge improves 0.268 to 0.264.
   Its width interval also reaches [+0.02, +5.68], so the gain is barely separable from
   zero.
3. **The two zones select different configurations**, so there is no single default to
   adopt even had both passed.

### What the phase established anyway

- **Sharpness is available and is not free.** A 4.5% narrower NL interval exists inside
  this grid, with an interval that excludes zero. It costs midday coverage.
- **Conformal coverage degrades with trend, measured rather than asserted.** At one
  fixed placement on NL: 0.897 (2024), 0.887 (2023), 0.847 (2022), 0.791 (2021), against
  monthly means climbing 77 to 238 EUR/MWh across 2021 H2.
- **A shorter calibration block sharpens.** `calib_fraction=0.2` dominates the
  leaderboard in both zones. This spec predicted the opposite ("a short calibration block
  buys a noisier and typically wider correction"): handing more data to the base learners
  beats the slightly more conservative conformal correction, and the predicted direction
  was wrong.
- **Extra capacity buys nothing.** The 800-tree block never beat 200 or 400 trees in
  either zone, so this grid's minimum sits at or below the shipped capacity.
- **The seed spread is structurally zero, and is not evidence of stability.** LightGBM
  runs here with `deterministic=True`, `n_jobs=1` and no bagging or feature subsampling,
  so `random_state` has no entry point into the fit. R2.8's seed-width rule was written
  for scenario *draw* noise and does not transfer to the forecaster; the day-block
  bootstrap is the only width this claim has.

### A metric question this phase raises and does not answer

`max_hour_deviation` is symmetric. It scores the incumbent's over-coverage at 21:00 and
the challenger's undercoverage at 11:00 on the same scale, and for a battery those are
not equally harmful: a too-wide interval wastes opportunity, a too-narrow one misprices
risk. A signed rule would have reached a different verdict on NL. Changing the metric
after watching it reject a candidate is not a change this phase can make, so it is
recorded here for a phase that can argue it on its own terms.

## Out of scope

- **A different base learner.** LEAR, DNN, N-BEATS and friends are a separate question with a separate motivation; this phase tunes what ships.
- **Feature and target settings.** `rolling_stats`, `season_encoding` and `normalize_target` were chosen in R2.1e and stay fixed, or this phase re-opens that one under a different name.
- **Split conformal.** It stays the constant-width baseline the coverage gate compares against, untuned.
- **Per-hour or per-season models.** A plausible sharpness win, and a different structure, not a hyperparameter.
- **Adaptive conformal (ACI) and conditional-coverage guarantees.** Already out of scope in §R2.1; unchanged here.
- **Changing the fold layout.** R2.7 settled it; this phase adds a disjoint tuning layout and touches nothing else.

## Decisions

- **Where do the tuning folds go?** *Proposed:* inside 2021, which the reporting layout uses only for training. **Resolved: in the gaps between the reporting blocks instead** (2026-08-31). 2021 is the worst-calibrated year in the span (coverage 0.791 against 0.897 in 2024, on the crisis ramp), so the incumbent misses the band there and nothing is selectable. The gap placement is disjoint on the same terms and matches the reporting regime and training window as well, so the weakness recorded in the next item disappears rather than being accepted. The alternative, splitting the 52 reporting folds in half, halves the reporting precision and drops the 2022 crisis year from one side or the other.
- **The tuning regime does not match the reporting regime.** Tuning trains on 180 days and reports on 365, and 2021 H2 is the crisis ramp rather than a typical year. *Proposed:* accept it and say so. **Resolved: no longer applies** (2026-08-31). The gap placement uses the reporting layout's own 365-day window and spans the same years, so the mismatch this item accepted is gone.
- **A trending regime is where conformal coverage degrades, and the span contains one.** Not asked at review, and the measurement above answers it: coverage falls monotonically with how hard the price level trends, from 0.897 in 2024 to 0.791 in 2021. *Resolved:* recorded as a finding, not acted on. R2.1 already names exchangeability as the critical assumption and R2.1b's drift monitor as the response; quantifying the degradation is a result this phase can report, and fixing it (adaptive conformal) is explicitly out of scope in §R2.1.
- **Why an exhaustive grid rather than random search or Bayesian optimization?** *Proposed:* 324 configurations at roughly 5 s each is under half an hour. Exhaustive removes the search seed from the result, which is one less width to report.
- **Should `calib_fraction` be in the grid at all,** given it is a conformal knob and not a learner knob? *Proposed:* yes. It moves width, the phase is about width, and leaving it out would mean tuning the learners around a calibration size nobody chose.
- **How are exact ties broken?** *Proposed at review:* by position in the frozen grid. **Resolved: by the cheaper model, then by a canonical parameter ordering** (2026-08-31). A property test showed grid position is not order-invariant, so a re-ordered grid could return a different model at identical width and the recorded result would not reproduce. Equal width for less capacity is also the better buy, so the replacement is a real preference rather than a coin toss.
- **What if the sharpest feasible config is sharper but its interval is no longer useful downstream?** *Proposed:* out of this phase's reach to detect statistically, which is why the euro re-run is in the gate rather than in a follow-up.
