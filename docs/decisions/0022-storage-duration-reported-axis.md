# ADR-0022: Storage duration is a reported axis for economic and value comparisons

**Status:** Accepted
**Date:** 2026-07-14

## Context

The optimizer math is scale-invariant in the asset's power and energy ratings:
the degradation cost $c^{\text{deg}}$ is €/MWh of throughput, the SoC balance is
per-unit, and the model reduces correctly at any energy-to-power ratio. That
invariance makes it tempting to report results for one representative asset (the
1 MWh / 1 MW, i.e. **1-hour**, worked-example battery) and treat duration as an
incidental config value.

But the *economics* and the *value of the Release-2 layer* are strongly
duration-dependent, and the qualitative conclusions flip across the 1h–4h range:

- **Revenue per MWh-installed** shows diminishing returns in duration: each added
  hour of storage captures a progressively smaller slice of the daily price
  spread (the first hour arbitrages peak-vs-trough, the fourth a much flatter
  part of the curve).
- **R1.4 capture ratio** $V^{\mathrm{roll}}/V^\star$ falls as duration rises,
  because cross-day (overnight) carry value grows with duration. A 1h asset sits
  near 99% (deterministic day-ahead arbitrage is a near-solved problem for it); a
  4h asset lands noticeably lower.
- **R2 value** (VSS, forecast value, overnight carry) scales with duration:
  near-zero headroom at 1h, real headroom at 4h. Reporting VSS at a single
  duration understates or overstates R2's general applicability.
- **Gate-D sanity band** uses $c=\eta^{rt}\,(\text{cycles/day})\cdot 365$, and
  cycles/day depends on duration.

A single-duration headline is therefore not merely incomplete: it can state a
general claim ("R2 adds little" / "R2 captures real value") that is actually a
property of the chosen duration.

## Decision

Treat **storage duration (energy-to-power ratio) as a first-class reported axis**
for every economic and value comparison. Concretely:

- The R1.4 capture ratio, and (once R2 lands) the VSS and forecast-value metrics,
  are reported across a small duration set. Default: **{1h, 2h, 4h}**, as a table
  or curve, not for a single asset.
- When a figure is quoted for one duration, the duration is named and the result
  marked duration-conditional.
- The gate-D sanity band recomputes cycles/day per duration rather than assuming
  a fixed value.

The formulation math is unchanged; this is a reporting and evaluation
requirement, not a model change.

## Consequences

- **Easier:** every reported headline carries its asset context, so the
  "R2 is / isn't worth it" conclusion is stated where it holds rather than
  overgeneralized. The duration sweep doubles as a validation that the
  rolling-to-ceiling gap behaves as physics predicts (it should widen with
  duration).
- **Harder:** the backtest and any R2 evaluation harness must parametrize over
  duration and aggregate; more solves and more table columns.
- **Enforced by:** the R1.4 backtest and the R2 evaluation report emit a
  duration-indexed result ({1h, 2h, 4h}); a single-duration headline in the
  README or `formulation.md` must state its duration. The R1.4 reporting note
  ([formulation.md: R1.4](../formulation.md#r14-backtest-semantics))
  points here; VSS is defined in
  [ADR-0007](0007-stochastic-value-requires-risk-or-recourse.md) and R2.3.

## Failure mode

The sweep is treated as boilerplate and one duration silently becomes "the"
number again (e.g. the README quotes the 1h capture ratio as the headline),
reintroducing the overgeneralization this ADR exists to prevent. **Signal:** a
capture-ratio or VSS figure in a committed doc or results table with no duration
stated. **Mitigation:** the R1.4 reporting note and this ADR.

## Alternatives considered

- **Single representative asset (1h), duration mentioned only in prose.**
  Rejected: the conclusions flip across durations, so a single number
  misrepresents the general case, most sharply for the value of R2.
- **Report only the extremes (1h and 4h).** Reasonable, but 2h is a common
  real-world procurement point and shows the curve is not linear, so the default
  keeps it. Not rejected outright: 2h may be dropped if the solve budget is tight.
- **Continuous duration sweep.** Over-built for a headline; three points
  communicate the trend without turning the result into a parametric study.
