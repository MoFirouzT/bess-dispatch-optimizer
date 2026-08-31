# Drift-robust conformal: which repair survives a regime shift?

**Interim, synthetic only.** The real-price run is pending an ENTSO-E outage, so nothing
here is an adoption decision. What it does settle is which knob values are worth
spending that run on, and it has already produced one finding that changes how the
weighted arm should be read.

Governing spec: [R2.1g](../specs/drift-robust-conformal.md).

*Assumes: the conformal construction in [formulation-uncertainty.md §R2.1](../formulation-uncertainty.md#r21-probabilistic-price-forecast-conformal-intervals-no-optimizer-change);
the coverage-versus-trend measurement in [R2.1f](../specs/interval-sharpness.md).*

## The question

The forecaster's coverage guarantee holds for exchangeable data, and prices are not
exchangeable. R2.1f measured what that costs: coverage falls monotonically with trend,
0.897 in 2024 down to 0.791 across the 2021 crisis ramp. Two published constructions
repair different halves of that, and this study asks which one earns its width.

- **Weighted conformal** discounts old calibration scores, and turns the coverage
  shortfall into a number you can state in advance.
- **Adaptive conformal inference (ACI)** moves the target level in response to realized
  misses, with a long-run guarantee that assumes nothing about the data.

## Method

Four seeded synthetic regimes, each a transformation of the same base series so only
the drift differs: **calm** (the control), **ramp** (level climbs to 3x), **changepoint**
(a single doubling halfway through), and **volatility** (spread doubles, level held).
That last one exists to separate the arms: it moves the scores without moving the level.

Each arm walks 290 delivery days sequentially, refitting every 120 days on a trailing
120-day window. An arm is feasible when it holds coverage inside [0.85, 0.95] on
**every** regime and its clamp binds on under 5% of days everywhere; among feasible
arms the winner minimizes the width it costs on the calm regime, since width bought
where there is no drift is width bought for nothing.

## What it found

**1. ACI moves coverage; weighting, on this instrument, does not.**

| arm | calm | ramp | changepoint | volatility | calm width |
| --- | --- | --- | --- | --- | --- |
| incumbent | 0.890 | 0.785 | 0.810 | 0.806 | +0.0% |
| weights, half-life 7d | 0.872 | 0.784 | 0.791 | 0.804 | -3.1% |
| weights, half-life 3d | 0.863 | 0.783 | 0.776 | 0.802 | -4.5% |
| ACI, $\gamma = 0.005$ | 0.891 | 0.852 | 0.864 | 0.858 | +0.1% |
| ACI, $\gamma = 0.01$ | 0.890 | 0.872 | 0.881 | 0.877 | +0.4% |

ACI lifts the worst regime from 0.785 to 0.852 while costing **0.1%** width on calm
data, because it only widens when it is actually missing. Weighting alone moves the
drifting regimes by roughly nothing and makes the changepoint regime *worse*.

**2. The weighted arm is high-variance across refits, and that is structural.**

Weighting looked much stronger on an earlier probe (0.776 to 0.837 on a ramp). Chasing
the disagreement rather than picking the flattering number is where the finding is. The
conformal margin at three successive refits of the same run, against the unweighted
margin:

| refit | unweighted | half-life 7d | half-life 3d |
| --- | --- | --- | --- |
| 1 | 9.545 | +0.850 | +0.850 |
| 2 | 8.943 | +0.944 | +1.643 |
| 3 | 11.297 | **-4.574** | **-7.043** |

At the third refit the weighted margin collapses by 40 to 60 percent. It is not a bug:
the most recent calibration quarter genuinely is better bracketed there (90th-percentile
score 2.59 against 19.27 in the oldest quarter), so discounting the older scores
correctly produces a narrower interval. Averaged over a run those swings cancel, which
is why the net width change is near zero and the coverage gain is not reliable.

The mechanism is the arm's own design. A 3-day half-life leaves an effective sample of
about $1/(1-\rho) \approx 104$ points out of 814, so the 90% quantile rests on roughly
ten effective observations in the tail.

**This is a real tension the governing theorem does not cover.** A shorter half-life
tightens the coverage-gap bound and shrinks the effective sample that estimates the
margin. Barber et al.'s Theorem 2a bounds the first and says nothing about the second,
so a half-life chosen to make the bound look good buys a noisier interval, and the
bound does not warn you.

**3. ACI's step size is picked by the clamp, not by coverage.**
On the changepoint regime, $\gamma = 0.005$ binds the clamp on 4.1% of days and
$\gamma = 0.01$ on 33.1%. A step change drives the level straight to the floor, and a
saturated arm is a fixed-level arm wearing ACI's name. Coverage alone would have chosen
the larger step.

## Selected for the real run

**Half-life `None`, $\gamma = 0.005$**: the only arm feasible on all four regimes.
Calm width +0.1%, worst-regime coverage 0.852, clamp binding at most 4.1%.

The weighted arm stays in the real run despite not being selected here. It is the only
one of the two that produces a *number*, and a 7-day half-life bounds the cost of a
one-week-old regime break at 0.5 coverage where unweighted conformal bounds it at 1.0,
which is to say not at all. Whether that bound is worth its variance is a question for
real prices.

## What this does not show

Synthetic drift, one seed, one refit schedule. The regimes were built to be
diagnostic rather than realistic, and the variance finding above is precisely a warning
that a single instrument can mislead. Coverage on real prices, the width paid on years
that are already calibrated, and whether NL and BE agree are all the real run's to
answer.
