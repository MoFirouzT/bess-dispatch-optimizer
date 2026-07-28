# Target normalization: does de-levelling the forecast target help?

**Answer: null at the shipped window, a real gain at two years, and it flips which
training window is best.** The headline metric barely moves, but the sweep it
enabled overturned an earlier conclusion about how much history to train on.

Governing spec: [R2.1e](../specs/R2.1e-target-normalization.md).

## The question

The forecaster predicts the price level directly. Electricity prices drift across
regimes (a gas crisis moves the whole level), so an alternative is to predict a
standardized target and invert it afterwards, using a trailing window's level and
scale that are both known before prediction time.

Because level and scale are known constants at prediction time and the scale is
positive, the inversion is a strictly increasing affine map, so the forecaster's
calibrated coverage is **inherited rather than re-derived**. That is what makes
the change cheap to justify.

## Result 1: the headline is a null

At the shipped 365-day configuration, hour-of-day conditional coverage deviation
moves from **0.0653 to 0.0622** for the conformalized quantile model and **0.0884
to 0.0815** for the split-conformal one. Marginal coverage holds at nominal
(0.900 to 0.902, interval [0.885, 0.919]). Pinball loss gains about 3% on the
lower edge and about 0% on the upper.

Recorded as a pass under the null-tolerant rule, and reported as a null.

## Result 2: the real finding is that it flips the window sweep

Measured on identical test days, pinball loss for the raw and normalized targets:

| Training window | Raw target | Normalized |
| --- | --- | --- |
| 90 days | **3.574** | 3.761 |
| 180 days | **3.674** | 3.796 |
| 365 days | 3.532 | **3.419** |
| 730 days | 3.711 | **3.405** |

Interval width at 730 days falls from 106.0 to 93.1.

There is a clean crossover at 365 days. De-levelling **hurts** short windows,
which are already roughly stationary, so it only adds estimation noise. It
**helps** long ones, which carry the regime drift it exists to remove.

Under the raw target, 730 days was the *worst* window available. Under
normalization it is the *best*, with the narrowest intervals. That answers a real
question about training data: **crisis history is harmful under a raw target and
useful under a de-levelled one.**

## Result 3: a pre-existing defect found on the way

The interval ordering `lower <= point <= upper` was asserted in two places and
violated in practice: the shipped model fits three independent quantile learners
and conformalizes only the lower and upper pair, so the median could fall outside
its own interval. **174 of 32,665** real predictions were out of order at the
365-day window.

`lower > upper` never occurred, so the interval always carried its guarantee and
no coverage number moves. Only the point estimate was affected, which is the field
the scenario layer consumes. The point is now clipped into its interval and the
clip count is surfaced so the fix cannot silently mask a bad median model.

Normalization eliminates the crossing entirely, **174 to 0**, which is an argument
for it independent of accuracy.

## What ships

Normalization is **off by default**. It is not better everywhere (it hurts at 90
and 180 days), which was the stated condition for flipping a default. The
recommended pairing is normalization with a 730-day window, documented rather
than defaulted.

A cyclical season encoding was measured again in the same sweep and is **not**
shipped: it costs pinball loss at both long windows and raises quantile crossing.
That negative result now rests on a measurement rather than on an artifact of a
short evaluation window.

## Reproduce

Token-gated, via the live forecaster tests:

```bash
uv run --group forecast pytest tests/integration/test_forecaster_live.py -s
```
