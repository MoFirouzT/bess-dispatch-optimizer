# Stochastic value: does hedging beat the mean forecast?

**Answer: yes, and it is a distribution rather than a constant.**
Over every UTC day of a real Dutch quarter, the two-stage stochastic commitment
beat the mean-value plan by a **median of +12.90 EUR per window**, positive on
**66% of 94 windows**, quartiles [−2.41, +31.37], for a 2 MWh / 1 MW asset.

*Measured live on 2026-07-28 over real NL day-ahead prices, 2024-03-01 to
2024-06-30, a 2 MWh / 1 MW asset at a 0.5 recourse budget.*

Governing spec: [R2.5](../specs/value-evaluation.md); protocol:
[the recourse and out-of-sample protocol](../decisions/risk-aware-two-stage-design.md); math:
[formulation-evaluation.md § R2.5](../formulation-evaluation.md).

## The question

The value of the stochastic solution (VSS) is the classical Birge-Louveaux answer
to "was the scenario machinery worth building?": the recourse-problem value minus
the value of the plan you get by optimizing against the mean forecast. A single
positive VSS on a designed instance proves only that the mechanism exists. This
study asks whether it survives on real days.

## Method

Each window is one UTC day. Commitments are fitted on the trailing 28 days, then
scored **fixed** on that day's realized prices, so nothing at or after the window
enters the fit. Both the stochastic (RP) and mean-value (EV) commitments are
scored the same way, with optimal within-budget intraday recourse.

Fitting and scoring being separate is the whole point: an in-sample VSS is
guaranteed non-negative by construction and would prove nothing.

## Result

The negative windows are real and reported. On a calm day the mean-value plan is
already fine, so the stochastic edge is a distribution whose median is positive,
not a constant.

![Per-window out-of-sample VSS on real NL 2024-Q2 days: a histogram of windows straddling zero with its median clearly positive.](../figures/example-vss-distribution.svg)

The mechanism behind it is the intraday recourse budget ρ, and the shape confirms
it: value **rises then falls** with ρ. At zero recourse the commitment cannot
adapt and at unlimited recourse the day-ahead plan stops mattering, so both ends
collapse to the mean-value plan and the value lives strictly in between. On real
NL 2024-Q2 the curve runs 0 at ρ = 0, peaks at **8.54** near ρ = 0.5, and returns
to 0.

Trading expected profit for downside protection traces a mean-CVaR frontier,
graded rather than a single point.

<table>
  <tr>
    <td width="50.7%"><img src="../figures/example-vss-curve.svg" alt="Value of the stochastic solution vs. the intraday recourse budget: zero at both ends, strictly positive in between."></td>
    <td width="50%"><img src="../figures/example-risk-return-frontier.svg" alt="Mean-CVaR risk/return frontier: raising the risk weight trades expected profit for a smaller downside."></td>
  </tr>
</table>

## Why this one is positive when three others are null

The stochastic *structure* earns money; the fancier *inputs* to it do not. This
study varies the decision rule (hedge across scenarios versus commit to the mean)
while the [forecast](forecast-value.md), [tail](tail-value.md), and
[bid-curve](bid-curves.md) studies vary the scenario set feeding a fixed rule.
Recourse can absorb a mis-specified input after the fact; it cannot manufacture a
hedge the commitment never made.

## Reproduce

```bash
uv run --group examples python examples/vss_study.py
```

Needs an ENTSO-E token; falls back to a synthetic series without one.
