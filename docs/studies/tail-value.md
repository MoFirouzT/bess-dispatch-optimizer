# Tail value: do priced spikes earn more euros?

**Answer: null, at every recourse budget.** On 64 real Dutch days the per-window
tail value has a **median of +0.00 EUR at every ρ** tested (0.1, 0.25, 0.5, 1.0),
means between +0.03 and +0.53, with only 8% to 25% of windows positive.

Governing spec: [R2.5b](../specs/R2.5b-tail-dispatch-value.md).

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
