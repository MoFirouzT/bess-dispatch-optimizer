# Spec R2.7: Study windowing

**Status:** Implemented
**Release:** R2  **Depends on:** R2.5, R2.5b, R2.6, R2.1d
**Phases:** R2.7

## Objective

Re-measure all four euro-denominated value studies over the full 2021 to 2025 NL
span on evenly spread fold blocks, instead of the single contiguous 2024 quarter
they currently rest on; report each result by regime as well as pooled, and repeat
the two headline studies on BE as a second-market check.

*Assumes:* the evaluation semantics in
[formulation-evaluation.md § R2.5](../formulation-evaluation.md#r25-value-evaluation-hardening-evaluation-semantics-no-optimizer-change);
the fold-placement machinery from [R2.1d](forecaster-evaluation.md); the window
construction in [R2.5](value-evaluation.md).

## Motivation

The forecaster had exactly this defect and fixed it. R2.1 reported "3 folds" that
turned out to be one contiguous fortnight, so every coverage number it published
was a mid-May statement dressed as a general one; R2.1d rebuilt the harness on
evenly spread folds across 4.7 years and re-measured everything.

The value studies still have the uncorrected version of that defect, one level up.
All four run on consecutive UTC days inside a single window, and three of the four
run inside the same one:

| Study | Window | Windows |
| --- | --- | --- |
| [Stochastic value](../studies/stochastic-value.md) | 2024-03-01 to 2024-06-30 | 94 |
| [Forecast value](../studies/forecast-value.md) | 2024-03-01 to 2024-06-30 | 94 |
| [Tail value](../studies/tail-value.md) | 2024-03-01 to 2024-06-01 | 64 |
| [Bid curves](../studies/bid-curves.md) | 2024-03-01 to 2024-05-01 | 33 |

That is one spring, in one year, in one price regime. The whole 4-month range sits
inside the level spread R2.1d measured across the span: NL yearly means run 102.97,
241.88, 95.81, 77.28 and 86.34 EUR/MWh over 2021 to 2025, roughly a 3x spread.

The consequence is already visible and already conceded. Moving the stochastic and
forecast studies from a Q2-only 63-window slice to the current 94-window one left
VSS almost unchanged (+12 to +12.90 EUR, 62% to 66% positive) but moved forecast
value from -0.9 EUR at 49% positive to -19.81 EUR at 41% positive. One of those two
findings is window-robust and one is not, and the project currently cannot say which
of its four headline results are which. The [studies README](../studies/README.md)
names this as the standing limitation across the value studies.

**The question this phase answers is not "what is the right number".** It is whether
each of the four findings is a property of a day-ahead market or a property of spring
2024. A span answers half of that and a second market answers the other half, which is
why BE is in scope here rather than deferred.

## Formulation reference

[`formulation-evaluation.md` § R2.5](../formulation-evaluation.md#r25-value-evaluation-hardening-evaluation-semantics-no-optimizer-change).
**No new section and no new quantity.** VSS, FV, tail value and bid-curve value are
computed by the formulas already there, unchanged.

One canonical edit is required, in the same change (CLAUDE.md §1). §R2.5 currently
says the reported object is the empirical distribution "over all windows with enough
history", which describes a contiguous sweep of whatever series was passed in. That
clause is replaced by an explicit window-selection protocol: the distribution is over
a declared set of delivery days, and the set is part of the claim. The quantities and
their sign-honesty rules are untouched.

**No optimizer delta.** No constraint, variable, objective term, or efficiency
placement changes; `docs/formulation.md` is untouched.

## Governing reference

**None required.** Fold placement over a span is R2.1d's own construction, already
in-house. The block bootstrap below is the same day-block resampling `coverage_ci`
already performs for pooled coverage, applied one level up to a median instead of a
proportion. Neither is new theory. *(Open for the human's call, per CLAUDE.md §1: the
moving-block bootstrap for dependent data has a standard published source, and if one
is wanted it must be verified by edition and section, not cited from memory.)*

## Data window

| Item | Value | Why |
| --- | --- | --- |
| Zone | NL (primary), BE (reduced second-market check) | Mirrors R2.1d's zone split; the BE span is already fetched and cached, so the marginal cost is solver time, not data |
| Span | 2021-01-01 to 2025-09-30 | Identical to R2.1d's evaluation span, verified there at 41,593 hourly points over 1734 days |
| Upper bound reason | The SDAC market time unit moved to 15 minutes at 2025-10-01 00:00 local | A window crossing the switch fails loudly in `validate_utc_index`; mixed resolution stays out of scope, as in R2.1d |
| Evaluated days | 260 per zone, in 52 blocks of 5 | The identical fold layout R2.1d gates the forecaster on, in both zones |
| Evaluated range | 2022-01-01 to 2025-09-29 | A 365-day training window must precede the first block; 2021 is training history, not evaluation |

### Build task 0 findings (probed 2026-07-28, from the on-disk cache)

Recorded here because the phase is designed against them, and because two of them
contradict what this spec assumed before the probe ran.

- **BE matches NL exactly on shape**: both spans return 41,593 hourly points over
  1734 calendar days at a single regular hourly step. The BE-specific risk this probe
  existed to retire (a second zone with a different step or a shorter history, which
  would have forced two fold layouts) is not present.
- **1733 of those 1734 days are complete.** The span's final day, 2025-09-30, carries
  a single point at 00:00 UTC, because the span's upper bound is a timestamp rather
  than a day. `window_sets` drops incomplete days, so placing folds over the raw
  day index selects 260 days of which only **259 are scoreable**, silently. Placing
  them over the **complete-day index** selects 260 of 260 and ends the span at
  2025-09-29. The spec takes the second option; see Decisions.
- **Blocks land 26 to 27 days apart, not the ~33 this spec first claimed.** The
  correction matters for the dependence argument, below.
- **Adjacent blocks' training sets overlap by 5 to 6 days out of 28.** The claim that
  blocks "share no training history at all" was wrong: a block's first window looks
  back 28 days across a 22-day gap. Non-adjacent blocks share nothing. The block
  remains the right resampling unit, but because between-block dependence is *small*
  rather than absent.
- **Regime balance of the 260 evaluated days**: 70 in 2022, 70 in 2023, 65 in 2024,
  55 in 2025. Yearly NL means over the span run 102.97, 241.91, 95.82, 77.29 and
  86.34 EUR/MWh, and BE tracks it closely at 104.12, 244.52, 97.27, 70.32 and 82.66.
  The evaluated set spans a 3x level range, against the single season it replaces.

**Fetching the span bypasses the R1.4c guard, deliberately.** `guarded_fetch`
classifies this span ANOMALY / `stuck_feed` on ordinary merit-order flats, which is a
known open defect in the guard's nonfocal rule and not a data problem
([STATE.md](../STATE.md)). R2.1d already works around it with a local `_span_prices`
helper. This phase reuses that workaround and moves it to a shared test fixture so it
is written down once; **fixing the rule stays out of scope**, and raising the constant
is explicitly not the fix.

## Design sketch

The fold layout is not merely similar to R2.1d's. It is the same call:

```python
rolling_origin_folds(days, n_folds=52, test_days=5, train_days=365, spacing="even")
```

over the same span, so the euro studies score **the identical 260 days** on which the
forecaster's pinball skill is gated. That alignment is the design's main point rather
than a convenience. The forecast-value study asks whether measured statistical skill
converts into dispatch euros; asking it on the same days makes the two answers
directly comparable instead of two claims about two different periods.

Three properties follow from blocks rather than a contiguous sweep:

1. **Regime coverage.** Blocks land 26 to 27 days apart (measured, build task 0) and
   traverse the crisis, the normalization, and the high-solar regime, so the pooled
   distribution is a statement about the span.
2. **Weaker dependence between scored days.** Consecutive windows inside a block share
   27 of their 28 training days, and their realized prices are serially correlated, so
   a contiguous sweep's effective sample is far below its window count. Across blocks
   that collapses: adjacent blocks share 5 to 6 training days out of 28, and
   non-adjacent blocks share none.
3. **Honest uncertainty.** Windows cluster inside a block, so the block is the
   resampling unit for a confidence interval on the median, exactly as the day is the
   resampling unit inside `coverage_ci`. Between-block dependence is small rather than
   zero, which the block bootstrap tolerates and a per-window sign test does not.

### The seeding defect this exposes

`window_sets` draws every window's training paths from one sequential generator, and
each study adds the window's **ordinal** to its scenario seed (`seed + i`). Both make
a window's result depend on which slice it was computed in. Scoring 2024-04-15 inside
a 4-month series and inside a 4.7-year series gives that day two different answers
today, from the same protocol and the same data.

That is tolerable for a single fixed sweep and fatal for a fold selection, where the
whole construction is "score this subset of days". The fix is to derive each window's
generator from `(seed, the window's date)`, so a window's result is a property of the
window. It gives the phase its central checkable invariant:

> **Selection is a filter, not a re-parameterization.** Scoring a subset of days must
> return exactly the same numbers as scoring every day and then discarding the rest.

That invariant is bitwise-checkable, needs no token, and is what makes the re-measured
numbers comparable to the old ones instead of merely different from them.

## Parameters / configuration

| Item | Where | Value | Change from R2.5 / R2.5b / R2.6 |
| --- | --- | --- | --- |
| window selection | studies harness | 52 even blocks of 5 days | was: every day in a contiguous series |
| span | live gates | 2021-01-01 to 2025-09-30 | was 2024-03-01 to 2024-05/06 |
| zones | live gates | NL for all four studies; BE for stochastic value and forecast value | was NL only |
| `train_days` (fold placement) | live gates | 365 | new; matches R2.1d |
| per-window RNG | `window_sets` | derived from `(seed, window date)` | was a sequential draw plus window ordinal |
| median uncertainty | live gates | block bootstrap over folds, 2000 resamples, level 0.95, fixed seed | was a one-sided sign test over windows |
| regime breakdown | studies harness | per calendar year | new |
| `history_days` | unchanged | 28 | unchanged |
| `n_scenarios` | unchanged | 30 (10 for bid curves) | unchanged |
| ρ | unchanged | 0.5 (VSS, FV); 0.25 and 1.0 (tail, bid curves) | unchanged |
| battery | unchanged | 2 MWh / 1 MW, anchored half-full | unchanged |

**Only the window set and the seeding change.** Every knob that could move a headline
number for a reason unrelated to windowing is pinned at its current value, so the
re-measurement has one variable, not five.

### Runtime budget

**Sized on real days, not on the synthetic estimate this spec was drafted with.**
Build task 0 timed one real mid-span block (2023-07-05, NL) per study and a forecaster
refit on a real 365-day training window:

| Study | s / window | Projected at 260 windows | Synthetic estimate it replaces |
| --- | --- | --- | --- |
| Stochastic value | 0.61 | 2.7 min | 2 min |
| Forecast value | 1.62 (+ 0.22 s per refit, 52 refits) | 7.2 min | 6 min |
| Tail value | 0.91 per ρ | 7.9 min at two ρ | 9 min |
| Bid curves | 3.36 per ρ | **29.2 min** at two ρ | 10 min |

**The bid-curve study is three times its synthetic estimate**, and alone accounts for
more than half the phase's runtime. Real prices carry many more distinct clearing
levels than the synthetic generator, and the contingent curve program grows with them.
NL therefore costs about 47 minutes and the two BE studies about 10 more, so the full
re-measurement is roughly **an hour**, not the 35 minutes assumed at approval.

That is too long to bolt onto the routine live tier, which runs in 16 minutes, so the
four re-measurement gates take their own `studies` marker and are run deliberately.
Deselecting is the right lever here rather than cutting windows: every alternative
(fewer blocks for bid curves, one ρ instead of two) buys minutes by making one study
incomparable to the other three, which is the one thing this phase exists to fix.

**The BE check stays reduced** for the same budget reason, following R2.1d's precedent
(its BE zone runs coverage at the default configuration only, not the sweep). BE runs
stochastic value and forecast value: one positive finding and one null, one gated and
one reported, which is the informative pair. Tail value and bid curves stay NL-only;
they are the two most expensive studies at two ρ each, and their nulls arise from the
same recourse mechanism the forecast-value study already probes on both zones.

## Interfaces

```python
# src/bess/studies/windows.py (additions)
def fold_days(folds: Sequence[Fold]) -> pd.DatetimeIndex
    # the union of the folds' test blocks, sorted, as UTC day starts

def window_sets(
    prices: pd.Series, *, history_days: int = 28, n_scenarios: int = 30,
    seed: int = 0, only_days: pd.DatetimeIndex | None = None,
) -> list[tuple[pd.Timestamp, ScenarioSet, ScenarioSet]]
    # `only_days=None` keeps today's behaviour: every day with enough history.
    # Per-window draws now derive from (seed, window date), so selection is a filter.

# src/bess/studies/summary.py (new)
@dataclass(frozen=True)
class WindowSummary:
    n_windows: int
    median: float
    q25: float
    q75: float
    share_positive: float
    median_ci: tuple[float, float]   # block bootstrap; (nan, nan) with one block

def summarize_by_block(
    values: np.ndarray, block_ids: np.ndarray, *,
    level: float = 0.95, n_boot: int = 2000, seed: int = 0,
) -> WindowSummary

def summarize_by_year(
    values: np.ndarray, window_starts: Sequence[pd.Timestamp],
) -> dict[int, WindowSummary]
```

`only_days` is threaded through the four study entry points as a keyword-only
argument, defaulting to `None`, so every existing call site keeps its current
behaviour: `vss_across_windows`, `fv_across_windows`, `tail_value_across_windows`,
`bid_curve_value_across_windows`.

`Fold` and `rolling_origin_folds` are imported from `bess.forecaster.evaluate`, which
`bess.studies` already depends on.

## Layering (import-linter)

No contract changes; the expected KEPT count stays **5**. `bess.studies` already
imports `bess.forecaster`, and nothing on the serving chain imports `bess.studies`.

## Build tasks

- [x] **0. Probe before speccing the numbers** (CLAUDE.md §7). Done 2026-07-28; see
      Build task 0 findings. It overturned three of this spec's assumptions: the block
      spacing, the between-block independence claim, and the runtime budget.
- [x] 1. Per-window RNG derived from `(seed, window date)` in `window_sets`; the
      per-study `seed + i` scenario seeds derived the same way.
- [x] 2. `only_days` filter in `window_sets`, with the filter-not-re-parameterization
      invariant under golden and property gates.
- [x] 3. `only_days` threaded through the four `*_across_windows` entry points.
- [x] 4. `fold_days`, and `src/bess/studies/summary.py` with the block bootstrap and
      the per-year breakdown.
- [x] 5. Shared span-fetch fixture in `tests/integration/conftest.py`, parameterized by
      zone and carrying the guard-bypass rationale, replacing R2.1d's local
      `_span_prices`.
- [x] 6. **Isolation run: re-measure the current 2024-03-01 to 2024-06-30 window under
      old and new seeding, before changing the window.** The re-measurement bundles two
      changes, and R2.1e's own lesson is that a bundled measurement produced a wrong
      reading that stood for days. This separates them: any movement left after the
      seeding is held fixed is attributable to the window.
- [x] 7. Live gates re-pointed at the 52-block layout, with the block-bootstrap median
      CI replacing the sign test, under a new `studies` pytest marker so the routine
      live tier keeps its 16-minute budget.
- [x] 7b. BE second-market run: stochastic value (gated on the same rule as NL) and
      forecast value (reported), same layout, same asset, same knobs.
- [x] 8. One-off cross-check: VSS full sweep over the span (about 1706 windows, roughly
      15 minutes) against the 52-block estimate, to show the sampling design does not
      itself move the median. Reported under Measured results, not gated.
- [x] 9. Regenerate the four study figures from the new runs; add a per-year figure for
      VSS and forecast value, which is where this phase's finding lives.
- [x] 10. Rewrite the four studies pages, the studies README (its standing-limitation
      paragraph is retired by this phase), and the repo README findings table. The two
      pages with a BE result state both zones; the two without say plainly that they
      are NL-only and why.
- [x] 11. §R2.5 window-protocol amendment plus changelog entry; amend
      [value-evaluation.md](value-evaluation.md)'s statistical-gate paragraph where it
      specifies the sign test, with a pointer here.

## Golden oracles

| # | inputs | expected | why this case |
|---|--------|----------|---------------|
| 1 | `fold_days` on a 400-day synthetic index, `n_folds=4, test_days=5, train_days=90, spacing="even"` | the exact 20 dates, hand-listed | pins the placement arithmetic and the inclusive/exclusive block edges |
| 2 | `window_sets(prices, only_days=D)` vs the `D`-subset of `window_sets(prices)` | identical starts, and **bitwise identical** scenario paths | the filter-not-re-parameterization invariant, at its source |
| 3 | `vss_across_windows(prices, only_days=D)` vs the `D`-subset of the unfiltered call | identical per-window `rp_oos`, `eev_oos`, `vss_oos` | the same invariant at the study level, where it is what makes fold scoring legitimate |
| 4 | `summarize_by_block` on a hand-built 12-value, 4-block vector | hand-computed median, quartiles, share positive | pins the summary arithmetic independently of the bootstrap |
| 5 | `summarize_by_block` where every block is identical | median CI collapses to the point median | the bootstrap adds no width where the data has no between-block variation |
| 6 | `summarize_by_year` on a synthetic series spanning 2023 and 2024 | the two years partition the windows, none lost, none counted twice | pins the regime split, which is the phase's reported object |

## Property tests

- **Filter commutes with scoring** for all four studies: scoring `only_days=D` equals
  subsetting the full result to `D`, for arbitrary `D` drawn from the scoreable days.
- A window's result is **invariant to the span it was computed in**: the same day
  scored inside a 3-month series and inside a 2-year series returns the same numbers.
  This fails on today's code and is the reason for build task 1.
- Fold blocks are non-overlapping, and every block has at least `history_days` days
  before its first day.
- `summarize_by_block`: the CI contains the point median; it is deterministic under a
  fixed seed; its width is non-increasing as blocks are added.
- `summarize_by_year`: the per-year window counts sum to the total, exactly.

## Statistical gates

Live and token-gated, never in CI, in the R2.1d style.

- **VSS, on NL and on BE**: the block-bootstrap 95% interval on the per-window median
  does **not** lie entirely below zero. This replaces the sign test, which assumes
  independent windows and is therefore wrong for blocked data. Same honesty rule as
  before: it fails on a genuine collapse to negative value, not on sampling noise, and
  it is not tuned to pass. BE is gated rather than merely reported for the reason
  R2.1d gates its own BE check: NL alone cannot separate "the stochastic layer earns
  its keep" from "NL happens to reward it".
- **In-sample ordering** EEV ≤ RP ≤ WS holds on every one of the 260 scored windows,
  in each zone.
- **Pinball skill** below 1 at both interval edges, unchanged from R2.1d and already
  measured on this exact span and layout.
- **Forecast value (NL and BE), tail value and bid-curve value**: medians, quartiles,
  share positive, block-bootstrap CI and the per-year breakdown are **reported with
  provenance, not sign-asserted**. Whether these convert to euros is the finding the
  studies exist to measure. A sign that moves under re-windowing, or across the border,
  is a result, and this phase exists precisely because it might.

**No gate asserts that a re-measured number resembles its predecessor.** If a
published finding does not survive the span, the finding was wrong and the page gets
rewritten. That direction is the deliverable, not a failure mode.

## Acceptance gate

*Blocks:* nothing downstream. Blocks the four studies pages and the README findings
table it rewrites. Every box must pass.

- [x] Golden oracles pass
- [x] Property tests pass, including the span-invariance test that fails on today's code
- [x] Live gates pass with a token, on the full 52-block layout, in both zones
- [x] The isolation run (build task 6) is recorded, separating the seeding effect from
      the window effect for each of the four studies
- [x] Figures regenerated from real-data runs only, and the studies pages state the new
      span and window count
- [x] ruff / format / mypy / lint-imports (5 KEPT) / docs-lint clean

## Measured results

Live runs of 2026-07-29, real NL and BE day-ahead prices, 260 evaluated days in 52
blocks over 2022-01-01 to 2025-09-29. The builder's record; the reader-facing write-ups
are in [studies/](../studies/).

### Build task 6: the seeding effect, isolated from the window effect

Both baselines reproduce the published numbers **exactly**, which is what makes the
rest of this table trustworthy rather than merely different.

| Measurement | VSS median | VSS >0 | FV median | FV >0 |
| --- | --- | --- | --- | --- |
| Published (Mar-Jun 2024, ordinal seeding) | +12.90 | 66% | -19.81 | 41% |
| Same window, date-keyed seeding | +9.12 | 60% | -16.08 | 35% |
| Full span, date-keyed seeding | +3.56 | 56% | -10.87 | 45% |

So the move splits about 40/60 for VSS: roughly **-3.8 EUR from the seeding**, a further
**-5.6 EUR from the window**. For FV both effects push the same way, toward zero.

**The seeding term is itself a finding, and not one this phase went looking for.**
Changing only *which* draws land on which day, holding protocol, window, asset and data
fixed, moved a headline of +12.90 by about 4 EUR. Neither seeding is more correct than
the other: both are valid draws from the same 30-scenario bootstrap. What the
comparison establishes is that the published median carried Monte Carlo noise of a
magnitude nobody had quantified, on top of the window sensitivity this phase set out to
measure. See the carried finding below.

### The distributions

| Study | Zone | Median | 95% CI | >0 |
| --- | --- | --- | --- | --- |
| Stochastic value | NL | +3.56 | [-1.03, +14.08] | 56% |
| Stochastic value | BE | +8.36 | [+4.57, +13.27] | 64% |
| Forecast value | NL | -10.87 | [-21.54, +5.17] | 45% |
| Forecast value | BE | -11.67 | [-27.26, +2.29] | 44% |

Per calendar year, medians in EUR per window:

| Year | VSS NL | VSS BE | FV NL | FV BE |
| --- | --- | --- | --- | --- |
| 2022 | +24.80 | +19.86 | -17.97 | -15.79 |
| 2023 | +10.87 | +8.49 | +8.08 | +8.16 |
| 2024 | +2.36 | +6.21 | -12.08 | +1.48 |
| 2025 | -2.27 | +8.06 | -17.33 | -48.52 |

Two things the single-quarter window could not have shown.

**VSS is far larger in the crisis year than after it.** NL reads +24.80 in 2022 against
roughly +2 in 2024, and BE +19.86 against +6.21. The stochastic edge is largest when
prices are most volatile, which is the mechanism working as designed, but it means the
headline is a statement about a regime rather than about the method. NL's pooled
interval now includes zero; BE's does not. Keeping BE is what turns "the claim
weakened" into "the claim is market-specific", and only the second is actionable.

**The per-year block medians are noisy, and build task 8 caught it.** At about 70 days
in roughly 14 blocks per year, a single year's median carries much more sampling error
than the pooled figure, and the cross-check below shows one reading that does not
survive: on the 52-block sample NL 2025 medians -2.27, but on every day of 2025 it
medians +1.10. **There is no monotone decay into negative territory**; there is a high
crisis year followed by three low, similar ones. Per-year rows are reported with their
intervals for exactly this reason and should not be read as a trend.

### Build task 8: does the 52-block sample track a full sweep?

Every scoreable NL day scored, 1705 windows in 15.0 minutes, against the 260-day block
estimate.

| Estimate | n | Median | >0 |
| --- | --- | --- | --- |
| Full sweep, all days | 1705 | +5.70 | 58% |
| Full sweep, 2022-01-01 onward (what the folds can reach) | 1368 | +4.37 | 55% |
| 52 blocks (the gate) | 260 | +3.56 | 56% |

The like-for-like comparison is the middle row against the last: **+4.37 against +3.56**,
a gap of 0.81 EUR, well inside the block estimate's own interval of [-1.03, +14.08], with
the positive share matching to a point (55% against 56%). The sampling design does not
move the pooled median materially, which is what this task existed to establish.

The sweep also re-derived the 52-block numbers **as a filter of itself** and reproduced
+3.56 / 56% exactly, matching the independently-run gate. That is the filter invariant
confirmed on real data at full scale, beyond the synthetic golden and property gates.

Per-year sweep medians, for contrast with the block rows above: 2021 +9.74, 2022 +19.75,
2023 +2.40, 2024 +1.50, 2025 +1.10. The crisis-year peak is robust; the year-to-year
ordering below it is not.

**Forecast value is a null that is not flat.** Pooled, both zones straddle zero and the
null holds. Underneath, 2023 is positive on both zones and BE 2025 is strongly negative
(-48.52, interval wholly below zero, 24% positive). The published -19.81 was the
pessimistic end of a range, not its centre.

### Tail value and bid curves: the nulls hardened

Both were already null on one quarter. On 260 days across four years they are null in
every year and at every recourse budget, which is a much stronger statement than the one
they replaced.

| Study | ρ | Median | 95% CI | >0 |
| --- | --- | --- | --- | --- |
| Tail value | 0.25 | +0.00 | [+0.00, +0.00] | 31% |
| Tail value | 1.0 | +0.00 | [+0.00, +0.00] | 9% |
| Bid-curve value | 0.25 | -0.00 | [-0.00, +0.00] | 35% |
| Bid-curve value | 1.0 | +0.00 | [+0.00, +0.00] | 24% |

No year reverses either sign. The tail study's positive share falls with the recourse
budget (31% to 9% at ρ = 0.25 and 1.0), which is the mechanism the nulls were always
attributed to: the more freely recourse can re-dispatch after the price is known, the
less a sharper day-ahead tail has left to buy.

**The bid-curve delivery gap survives, and it is the one number that grew.** Median
4.26 MWh per day at ρ = 0.25 and 7.91 at ρ = 1.0, maximum 14.02, on a 2 MWh asset.
R2.6 measured 4 to 8 MWh per day on one quarter and called it unpriced; four years and
260 days put the same range under it. Unlike the euro nulls, this is a claim the wider
window strengthened rather than weakened.

The bid-curve study also scored all 260 windows, against 33 on its published quarter,
so the skipping caveat its page carries no longer binds.

### Carried finding: scenario-draw noise is unquantified

The seeding comparison above establishes a third source of uncertainty in every euro
number this project reports, beside window choice and within-block dependence: the
Monte Carlo draw of the 30-scenario bootstrap itself. On the published window it is
worth about 4 EUR of median VSS, which is a third of the claim it sits under.

This phase deliberately fixes one variable, so measuring it is out of scope here: it
needs the studies re-run across many seeds, which is a different experiment from
re-windowing. It is recorded rather than absorbed, because a number whose noise is
unmeasured is a number whose precision is unknown. Any future phase that reports a
tighter VSS claim should quantify this first.

## Out of scope

- **Fixing the R1.4c stuck-feed rule.** It stays an open blocker; this phase reuses and
  documents the existing bypass, and does not raise the constant.
- **15-minute resolution**, and therefore any data after 2025-09-30.
- **Tail value and bid curves on BE**, and any zone beyond NL and BE. The BE check is
  deliberately reduced to the two headline studies; see the runtime budget.
- **Any knob sweep.** ρ, `n_scenarios`, `history_days` and the battery stay fixed; a
  phase with two variables cannot attribute what it finds.
- **Any optimizer or formulation math change.**
- **Promoting `_net_to_pair`** out of `bess.stochastic.vss` (a separate small follow-up
  recorded in [STATE.md](../STATE.md)).

## Decisions

Phase-local decisions only. Each was posed with a proposed answer and resolved in
place at review, so this reads as the decision trail rather than a list of questions.

- **Reuse R2.1d's exact fold layout, or place folds independently?** **Resolved: reuse
  it verbatim** (2026-07-28). *Proposed:* reuse
  it verbatim (52 blocks, 5 days, `train_days=365`, even). The euro studies then score
  the same 260 days the forecaster's skill is gated on, which is what makes "skill did
  not convert to euros" a statement about one set of days rather than two.
- **`train_days=365` excludes 2021 from evaluation. Accept?** **Resolved: yes**
  (2026-07-28). *Proposed:* yes. It is the cost of the alignment above, and 2022 to
  2025 still spans the crisis, the normalization and the high-solar regime, a 3x level
  range against the current window's one season. Dropping to `train_days=28` would
  recover 2021 at the cost of giving the forecast-value study folds with too little
  training history to be comparable to each other. **Consequence to state on the
  studies pages:** the calm pre-crisis regime is training history only, so a finding
  measured here is a statement about 2022 onward, not about 2021.
- **Replace the sign test with a block-bootstrap CI?** **Resolved: yes**
  (2026-07-28). *Proposed:* yes. The sign test
  assumes independent windows; blocked days are not independent, and a contiguous
  sweep's windows never were either. The bootstrap is also the only one of the two that
  produces a number the studies pages can quote.
- **Seed per window date rather than per ordinal?** **Resolved: yes** (2026-07-28).
  *Proposed:* yes, with the isolation
  run in build task 6 to keep the seeding effect separable from the window effect. The
  alternative, keeping ordinal seeds, makes fold-selected results non-reproducible from
  any other slice, which defeats the phase.
- **Also run the full sweep, not only the folds?** **Resolved: VSS only, once**
  (2026-07-28). *Proposed:* for VSS only, once, as
  the cross-check in build task 8. It costs about 15 minutes and it validates the
  sampling design itself. The other three are 1 to 2 hours each and would buy little
  once the VSS cross-check has shown the block estimate tracks the sweep.
- **Add BE as a generality check?** **Resolved: yes, reduced** (2026-07-28). *Proposed:*
  no, out of scope. Overturned at review: the phase's question is whether a finding is a
  property of a market or of one window, and a second market tests the first half of
  that as directly as the span tests the second. Reduced to stochastic value and
  forecast value, on R2.1d's precedent for its own BE zone, because the two remaining
  studies cost two ρ each and probe the same recourse mechanism forecast value already
  covers. Data cost is nil: the BE span is cached.
- **Place folds over the raw day index or the complete-day index?** **Resolved:
  complete-day index** (2026-07-28). Not anticipated at approval; build task 0 found
  it. The span's final day holds one hour, so the raw index selects a day that
  `window_sets` then silently drops, giving 259 scoreable windows where the layout
  promised 260. Selecting over complete days makes the promised count and the
  delivered count the same number, which is the property the fold layout has to have
  if "the identical 260 days" is to mean anything. Cost: the evaluated span ends
  2025-09-29 instead of 2025-09-30.
- **Do the re-measurement gates run in the routine live tier?** **Resolved: no, they
  take a `studies` marker** (2026-07-28). Also not anticipated at approval. Build task
  0 measured the four studies at about an hour against the 35 minutes assumed, driven
  by the bid-curve study running 3x its synthetic estimate on real prices. Cutting
  blocks or ρ values would buy the minutes back by making one study incomparable to
  the others, which is the defect this phase exists to remove, so the run is
  deselected instead of shortened.
- **Does this phase need a governing reference?** **Resolved: no** (2026-07-28).
  *Proposed:* no, per the Governing
  reference section. Raised because CLAUDE.md §1 makes this the human's call rather
  than an automatic step.
