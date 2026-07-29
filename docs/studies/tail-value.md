# Tail value: do priced spikes earn more euros?

**Answer: null, at every recourse budget and in every year.** On 260 Dutch delivery
days spread over four years the per-window tail value has a **median of +0.00 EUR**
at both budgets re-measured (ρ = 0.25 and 1.0), with 95% intervals of [+0.00, +0.00]
and 31% and 9% of windows positive.

*Re-measured live on 2026-07-29 over 260 days in 52 blocks, 2022-01-01 to 2025-09-29.
The original finding stands on 64 days of one 2024 quarter, at ρ = 0.1, 0.25, 0.5 and
1.0.*

Governing specs: [R2.5b](../specs/tail-dispatch-value.md) for the method,
[R2.7](../specs/study-windowing.md) for the window set.

## What changed: nothing, which is the point

This is the one study the wider window **strengthened without qualification**. A null
on one quarter is weak evidence; a null in every year of a span containing the gas
crisis, the normalization, and the current high-solar regime is strong evidence. No
year reverses the sign, and no recourse budget does either.

One number did sharpen the explanation. The share of positive windows falls from 31%
at ρ = 0.25 to **9% at ρ = 1.0**: the more freely recourse can re-dispatch once prices
are known, the less a sharper day-ahead tail has left to buy. That gradient was the
assumed mechanism before; now it is measured.

## The question

Two earlier refinements made the scenario set's tail measurably more faithful: an
extreme-value (peaks-over-threshold) tail so a scenario can price a spike beyond
the historical maximum, and a residual-load-conditional scale so spikes
concentrate on tight-margin hours. Both improved the *representation*.

A sharper representation is not the same as more money. For a battery the tail is
supposedly the decision-relevant part of the distribution, since a scarcity spike
is exactly the hour to have saved charge for. This study asks whether that
reasoning survives contact with realized euros.

It also served as a go/no-go: a further tail refinement was on the roadmap and
this result is why it stays unbuilt.

## Method

Feed the two-stage dispatch two scenario sets built from the same residuals and
the same seed, differing only in whether the extreme-value tail is spliced on.
Score both commitments on the realized path, with the day-ahead leg settling at
the **realized** price so a commitment that correctly anticipates a spike earns
it and one that anticipates a spike that never comes loses.

## The correction that made the result trustworthy

The settlement basis was originally specified as a shared *forecast* basis, and
that was wrong in a way that would have manufactured this null. Settling the
day-ahead leg at a forecast price structurally penalizes the tail: its extra
day-ahead trades settle at a flat forecast price, earning nothing while still
costing degradation, so tail value came out non-positive almost by construction.

A designed-instance measurement caught it. Under corrected realized-price
settlement the same designed spike instance gives tail value **+113 at ρ = 0
falling to 0 at ρ = 1**, which is the right shape, and the golden oracle asserting
a positive value on that instance holds.

That is what separates this null from a broken comparison: the machinery
demonstrably detects tail value where tail value exists.

## Why

Intraday recourse already captures a realized spike after the fact. Reserving
charge in the day-ahead commitment for a spike that recourse can exploit anyway
buys nothing, and reserving for a spike that does not arrive costs something.

Same mechanism as the [forecast-value](forecast-value.md) and
[bid-curve](bid-curves.md) nulls.

## Consequence

The scenario generator is refined enough for this asset and this market. Further
tail work was stopped on the strength of this measurement rather than on taste,
which is the useful kind of negative result: it redirects effort.

No figure. A null needs no chart.

## Reproduce

Token-gated, via the live integration test:

```bash
uv run pytest tests/integration/test_study_tail_value_live.py -s
```
