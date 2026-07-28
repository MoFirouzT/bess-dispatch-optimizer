# Target normalization: does de-levelling the forecast target help?

**Answer: yes.** Conditional calibration improves by 24% with *tighter* intervals,
and the sweep it enabled overturned an earlier conclusion about how much history to
train on: the best training window flips from one year to two.

Governing spec: [R2.1e](../specs/target-normalization.md).

## The question

The forecaster predicts the price level directly. Electricity prices drift across
regimes (a gas crisis moves the whole level), so an alternative is to predict a
standardized target and invert it afterwards, using a trailing window's level and
scale that are both known before prediction time.

Because level and scale are known constants at prediction time and the scale is
positive, the inversion is a strictly increasing affine map, so the forecaster's
calibrated coverage is **inherited rather than re-derived**. That is what makes
the change cheap to justify.

## Result 1: conditional coverage improves

At the shipped configuration, hour-of-day conditional coverage deviation moves from
**0.0653 to 0.0498** for the conformalized quantile model. Marginal coverage holds at
nominal (0.9003 to 0.9008, interval [0.883, 0.916]), and mean interval width tightens
slightly, from 138.3 to 134.8 EUR/MWh. Pinball skill against a seasonal-naive baseline
is unchanged at 0.219 / 0.280 at the two edges.

That is a 24 percent reduction in the deviation, with **tighter** intervals rather
than the usual widening, which is exactly what the phase was aimed at.

*A correction worth keeping visible:* an earlier reading called this line a null, at
0.0653 to 0.0622. That figure came from a configuration bundling all three changes,
including the cyclical season encoding that "What ships" below records as harmful. Once the
encoding is dropped, which is what ships, the improvement is roughly four times
larger. The ordinary lesson about compound changes: measuring a bundle measures the
bundle, not the part worth keeping.

*Re-measured live on 2026-07-28 over NL and BE, 2021-01-01 to 2025-09-30, 260 test
days.*

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
