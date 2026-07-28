# Forecast value: does a better forecast earn more euros?

**Answer: null.** Over 63 real Dutch days the forecast-value distribution is
centred on zero (**median −0.9 EUR per window**, **49% of windows positive**,
quartiles −41 to +31), despite the conformal forecaster having clear and measured
statistical skill over the seasonal-naive baseline it is compared against.

Governing spec: [R2.5](../specs/R2.5-value-evaluation.md); math:
[formulation-evaluation.md § R2.5](../formulation-evaluation.md).

## The question

The forecaster is demonstrably better by statistical measures: calibrated 90%
intervals, and pinball loss at the interval edges running **0.36x / 0.16x** a
seasonal-naive baseline's under the same walk-forward. The question this study
asks is the one that actually matters to the asset: does that skill convert into
dispatch euros?

Holding a forecast layer to a euro standard rather than a statistical one is the
point. A project can improve pinball loss indefinitely without the battery
earning a cent more.

## Method

Feed the *same* two-stage dispatch two scenario sets that differ only in the
forecast behind them: conformal versus seasonal-naive, with the forecaster refit
walk-forward. Compare realized-path profit per window.

Each commitment settles its day-ahead leg at its **own** mean, so each forecaster
is held to the price basis it believed in. The metric is antisymmetric in its two
inputs and returns exactly zero when they are identical, which is pinned by a
property test.

## Result

![Per-window forecast value on real NL 2024-Q2 days: a histogram of 63 windows straddling zero with its median at roughly zero.](../figures/example-fv-distribution.svg)

Single windows swing **±180 EUR** either way, which is why no single-window number
is quoted anywhere in this project. Quoting one would be cherry-picking from a
distribution whose centre is zero.

## Why

The scenario spread plus intraday recourse already hedge day-shape error. By the
time the point forecast would have paid off, the recourse has re-dispatched
against the realized price and captured the same value without it.

This is the first appearance of the mechanism that also produced the
[tail](tail-value.md) and [bid-curve](bid-curves.md) nulls: **recourse adjusts
after the price is known**, so a better day-ahead picture has little left to buy.

## What this does not say

It does not say the forecaster is worthless. It says its *marginal* dispatch value
over a seasonal-naive baseline, on this asset and this window, is not
distinguishable from zero. The forecaster still supplies the calibrated spread the
scenarios are drawn from, and the [stochastic structure](stochastic-value.md)
built on those scenarios does earn real money.

The honest claim is exactly that split: the structure pays, the sharper forecast
does not yet.

## Reproduce

```bash
uv run --group examples python examples/vss_study.py
```

Needs an ENTSO-E token and the `forecast` dependency group.
