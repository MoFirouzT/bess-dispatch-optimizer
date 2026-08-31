# Interval sharpness: can the forecaster's intervals be made narrower?

**Answer: yes, and the gate refused to buy it.** An exhaustive search over 324
hyperparameter configurations found a Dutch interval **4.5% narrower** than the shipped
one (+6.22 EUR/MWh, 95% interval [+3.17, +9.35]) at unchanged marginal coverage. It was
rejected because the narrowing lands unevenly across the day: it fixes wasteful
over-coverage at 21:00 and pushes 11:00 into real undercoverage. Nothing in the shipped
model changed.

Governing spec: [R2.1f](../specs/interval-sharpness.md).

## The question

The forecaster's three quantile learners have run at LightGBM's defaults since R2.1,
with 200 trees. Those numbers were never chosen against an objective, only frozen.

Conformal calibration makes choosing them a search over **width alone**. Whatever the
quantile models do, the conformal step moves the interval's bounds until marginal
coverage lands near the nominal 90%, so a worse base model does not produce an
uncovered interval, it produces a wider one. Coverage is therefore a constraint to
check, not a thing to optimize, and width is what hyperparameters actually move.

Width is also the input the dispatch layer consumes: the scenario set is drawn from the
interval, so width sets the spread of the price paths the optimizer hedges across. This
is a different question from forecast accuracy, which
[forecast value](forecast-value.md) already measured and found does not convert into
euros.

## How candidates were chosen without touching the gate's days

Selecting a model on the same days the gate later scores would make the winner's margin
partly a fit to those days. The reporting layout places 52 five-day blocks across
2022-2025 and leaves roughly 22 clear days between consecutive blocks, so the search
scores its candidates on **twelve blocks placed in those gaps**, with the same 365-day
training window. No day the gate scores was ever used to choose.

The spec originally put the tuning blocks in 2021, which the reporting layout uses only
for training. That had to be abandoned, and why is a result in itself (below).

## Result 1: sharpness exists and is not free

Reporting folds, 260 delivery days, both zones:

| | NL shipped | NL candidate | BE shipped | BE candidate |
| --- | --- | --- | --- | --- |
| mean width (EUR/MWh) | 138.35 | **132.15** | 135.85 | **132.99** |
| marginal coverage | 0.900 | 0.896 | 0.903 | 0.901 |
| coverage 95% interval | [0.883, 0.916] | [0.878, 0.913] | [0.886, 0.920] | [0.882, 0.918] |
| worst hour's deviation | 0.065 | 0.070 | 0.058 | 0.054 |
| pinball skill, lower / upper edge | 0.219 / 0.280 | 0.213 / 0.266 | 0.192 / 0.268 | 0.196 / 0.264 |

The Dutch width reduction is +6.22 EUR/MWh with a day-block interval of [+3.17, +9.35]
and 57.3% of days narrower, so it is not a sampling artifact. The Belgian one is +2.87
with an interval of [+0.02, +5.68], which barely clears zero.

**Why it was rejected.** The Dutch candidate's worst hour moves from 0.065 to 0.070, and
the two numbers are not the same failure. The shipped model's worst hour is **21:00 at
0.965**: it over-covers, so its interval is wastefully wide at the evening peak. The
candidate's worst hour is **11:00 at 0.830**: it under-covers. Hours 10 to 12 move from
0.861 / 0.857 / 0.849 to 0.842 / 0.830 / 0.861. The candidate is narrower at *every*
hour, which is exactly why it fixes one problem and creates the other.

The Belgian candidate passes that test but loses pinball skill at the lower interval
edge (0.192 to 0.196). The two zones also selected different configurations, so there
was never a single default to adopt.

## Result 2: conformal coverage degrades with trend

The 2021 tuning placement failed because 2021 is the worst-calibrated year in the span.
At one fixed placement on Dutch prices, pooled coverage runs:

| Year | Coverage | Monthly price level |
| --- | --- | --- |
| 2021 | 0.791 | 77 climbing to 238 EUR/MWh across H2 |
| 2022 | 0.847 | crisis peak |
| 2023 | 0.887 | |
| 2024 | 0.897 | |

Conformal prediction assumes exchangeability, and a hard upward trend in the price level
breaks it. The shipped model itself misses the coverage band in 2021, so no candidate
was selectable there at all.

R2.1 has always named exchangeability as the critical assumption and the drift monitor
as the response. This puts a number on how much it costs.

## Result 3: two things that were expected and are wrong

**A shorter calibration block sharpens.** The spec predicted that shrinking the
conformal calibration set would buy a noisier and therefore wider correction. The
opposite happened: `calib_fraction=0.2` dominates the leaderboard in both zones, because
handing more data to the base learners beats the slightly more conservative correction.

**Extra capacity buys nothing.** The 800-tree configurations never beat 200 or 400 in
either zone, so this grid's minimum sits at or below the capacity already shipped.

## What this means for the calibration problem

[Target normalization](target-normalization.md) already measured a better answer to the
problem that sank the Dutch candidate. On the same folds, de-levelling the forecast
target moves the worst hour's deviation from **0.065 to 0.0498** while *also* tightening
mean width to 134.8 EUR/MWh. That beats this study's rejected candidate on both axes:
better conditional calibration and nearly as narrow.

Normalization is off by default because it is not better everywhere (it hurts at 90- and
180-day training windows), with the recommended pairing being normalization at 730 days.
This search held it at its shipped value and never combined the two. **Running the same
search on top of the normalized target is the obvious next question**, and it is the one
most likely to get the width without the midday cost.

## A metric question this study raises and does not answer

The constraint that rejected the Dutch candidate is symmetric: it scores the shipped
model's over-coverage at 21:00 and the candidate's undercoverage at 11:00 on the same
scale. For a battery those differ. A too-wide interval wastes opportunity; a too-narrow
one misprices risk. A signed rule would have reached the opposite verdict.

Rewriting a metric after watching it reject a candidate is not a change the study that
watched it can make, so it is recorded here for one that can argue it independently.

## Reproduce

Token-gated, and slow: the search fits 324 configurations per zone, about 65 minutes
each.

```bash
uv run --group forecast pytest tests/integration/test_sharpness_live.py -s -m studies
```
