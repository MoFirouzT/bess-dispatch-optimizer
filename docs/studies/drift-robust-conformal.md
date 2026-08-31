# Drift-robust conformal: which repair survives a regime shift?

**Answer: neither, at a realistic refit cadence.** On real prices both constructions add
at most **+0.019** worst-year coverage against an adoption threshold of +0.03, and
nothing on BE. The finding that survives is the one that was masking them: moving the
forecaster's refit from annual to monthly is worth **+0.18** coverage on the crisis year
and a **35% narrower** interval, which is a scheduling change and no new theory at all.
One year is still unscored, and it is the worst one, because the fetch that would reach
it is blocked.

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

## Selected for the real run (superseded by the real run below)

**Half-life `None`, $\gamma = 0.005$**: the only arm feasible on all four regimes.
Calm width +0.1%, worst-regime coverage 0.852, clamp binding at most 4.1%.

The weighted arm stays in the real run despite not being selected here. It is the only
one of the two that produces a *number*, and a 7-day half-life bounds the cost of a
one-week-old regime break at 0.5 coverage where unweighted conformal bounds it at 1.0,
which is to say not at all. Whether that bound is worth its variance is a question for
real prices.

## On real prices: a null, and a bigger finding underneath it

The cached 2021-2025 span (both zones, 1369 scored days from 2022-01-01) was run while
the extended fetch stayed blocked. 2021 is warm-up here, so the worst scoreable year is
**2022**, the crisis year.

The first run used an **annual** refit and produced a dramatic result: the NL baseline
covered 2022 at 0.689, and weighting lifted it to 0.836, the composed arm to 0.864.
Those numbers are not reported as a finding, because R2.1f measured 2022 at 0.847 and
that gap was the protocol, not the market. Refitting once a year leaves the model fitted
on 2021 data serving the whole of the crisis, which is a staler forecaster than the
project publishes anywhere.

Rerun at a **monthly** refit, which is what the block harness effectively does:

| arm | NL 2022 | NL worst yr | NL width | BE 2022 | BE worst yr | BE width |
| --- | --- | --- | --- | --- | --- | --- |
| symmetric unweighted | 0.870 | 0.870 | +0.0% | 0.890 | 0.890 | +0.0% |
| weights only | 0.886 | 0.884 | -0.5% | 0.898 | 0.884 | -0.1% |
| ACI only | 0.893 | 0.885 | -1.4% | 0.900 | 0.883 | -1.9% |
| both | 0.889 | 0.889 | +1.4% | 0.898 | 0.886 | +1.6% |

**The phase's own gate says no.** Best worst-year gain is **+0.019** on NL and **nothing**
on BE, against an adoption threshold of +0.03. ACI's clamp binding falls from 19.4% to
0.0%, so the saturation that failed the gate at annual cadence was also an artefact of
the stale baseline. Every arm now sits within 2% of the baseline width, so the width cap
passes trivially and there is simply no coverage left to buy.

**The finding worth keeping is the one that was in the way.** Moving the refit from
annual to monthly is worth **+0.18 coverage** on the NL crisis year and a **35% narrower**
interval (median 184.90 to 120.06 EUR/MWh). That dwarfs anything either published
construction delivers here, costs no new theory, and is a scheduling change rather than a
calibration one. The coverage decay R2.1f attributed to exchangeability failure is, at
this cadence, mostly **model** staleness rather than **calibration** staleness.

**What is still untested.** R2.1f's worst year is 2021 at 0.791, and 2021 cannot be
scored without the extended span the ENTSO-E outage is blocking. The arms are being
judged here on a 0.870 starting point, not a 0.791 one, and a construction that adds
+0.019 where there is little to repair may do more where there is more. That is the run
this study still owes.

## What this does not show

Synthetic drift, one seed, one refit schedule for the selection; and on real prices, one
span that excludes the worst year in the data. The regimes were built to be diagnostic
rather than realistic, and the reversal between the synthetic selection (ACI) and the
real-price ranking (weighting, then neither) is itself the warning that a single
instrument misleads. Coverage on the 2021 ramp, and whether either arm earns its width
where the baseline is genuinely broken, are still open.
