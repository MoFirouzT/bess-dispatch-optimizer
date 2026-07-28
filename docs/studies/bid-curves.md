# Bid curves: does a price-contingent commitment pay?

**Answer: null on euros, but it surfaced a real unpriced exposure.**
On 33 real Dutch days the bid-curve value has a **median of −0.00 EUR at ρ = 0.25**
(mean −0.40, 30% of windows positive) and **+0.00 at ρ = 1.0** (mean +0.42, 12%
positive). The number that is **not** null is the delivery gap.

Governing spec: [R2.6](../specs/R2.6-bid-curves.md); math:
[formulation-uncertainty.md § R2.6](../formulation-uncertainty.md).

## The question

A day-ahead auction does not accept a schedule. It accepts a monotone
(price, quantity) curve per hour, and the clearing price decides which point on
that curve becomes your commitment. Every participant submits a curve, including a
pure price taker, so this is uncertainty handling rather than market power.

Modelling it properly means the commitment becomes a *function* of the hour's
clearing price instead of a fixed number. This study asks whether that contingency
is worth its considerable modelling cost.

## Method

Fit a curve commitment and a scalar commitment on the **same** training scenarios,
resolve the curve at the realized clearing prices, and score both identically as
quantity obligations entering the recourse budget. Scoring them the same way is
what makes the difference attributable to contingency rather than to the
evaluation.

## Result: the euros are a null

The mechanism is real and the implementation detects it. On a designed instance
the curve value runs **+28.79 at ρ = 0, +28.54, +24.69, +11.80, and +0.00 at
ρ = 1**, the expected monotone decay as recourse takes over. On real days it does
not survive.

The mildly negative mean at the tight budget is the honest out-of-sample cost of
fitting a commitment more tightly to training scenarios.

Same mechanism as the [forecast-value](forecast-value.md) and
[tail-value](tail-value.md) nulls: recourse adjusts after the price is known.

No figure. A null needs no chart.

## The finding that is not null: the delivery gap

The commitment promises **more volume than the battery can deliver**, and this
study does not charge for it.

| Recourse budget | Median gap, curve | Median gap, scalar |
| --- | --- | --- |
| ρ = 0.25 | 4.00 MWh | 4.21 MWh |
| ρ = 1.0 | 7.91 MWh | 9.91 MWh |

On a **2 MWh** asset, a promise of 4 to 8 MWh over a day is several times the
battery's capacity. Imbalance settlement is what would price that shortfall, and
imbalance settlement is not modelled here.

Two things follow. The contingency does buy something real: the curve's gap is
**smaller** than the scalar's at both budgets, so a price-contingent commitment
over-promises less, just not in a way this settlement rewards with euros. And this
is the most direct argument in the project for an imbalance-settlement stage being
the right next phase.

## Stated limitations

The study runs at **10 scenarios** where the other value studies use 30. The
curve program's monotonicity chain couples every commitment branch, so its solve
cost grows steeply in the scenario count. That is a stated approximation, not a
hidden one, and it costs scenario-set fidelity. Scaling it is a decomposition
problem rather than a tuning problem.

A curve's realized commitment is assembled across branches hour by hour, so it is
not generally a feasible schedule for the battery: over 30 trials it was
deliverable **0 times**, with a median terminal-state miss of 1.38 MWh. The
binding obstruction is the terminal-state equality. That is why the commitment is
scored as a cash-flow obligation rather than as a schedule, and the unpriced
residual of that choice is exactly the delivery gap above.

## Reproduce

Token-gated, via the live integration test:

```bash
uv run pytest tests/integration/test_study_bid_curve_live.py -s
```
