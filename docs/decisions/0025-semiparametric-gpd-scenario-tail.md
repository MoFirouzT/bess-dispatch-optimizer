# ADR-0025: Semiparametric GPD tail for the scenario bootstrap (splice, not resample or re-model)

**Status:** Accepted
**Date:** 2026-07-24
**Supersedes / Superseded by:** None

## Context

The R2.2 residual-path bootstrap ([ADR-0017](0017-residual-path-bootstrap-generation.md))
generates price scenarios by resampling whole-day forecast-error vectors with
replacement. It preserves intra-day error correlation but is **bounded above by
history**: the largest spike any scenario can contain is the historical-maximum
residual. So the R2.3 risk-aware program, and its CVaR tail, are blind to any spike
larger than the calibration window has seen. R2.2b (spec
`docs/specs/R2.2b-spike-tail.md`) adds an extreme-value tail to fix this.

Three ways to add a tail were considered: replace the whole generator with a
parametric model; add separate synthetic extreme scenarios; or splice a parametric
tail onto the existing empirical draws.

## Decision

**Semiparametric splice, in place.** Keep the empirical whole-day bootstrap for the
body (intra-day shape, equiprobable `p_s = 1/n`, same scenario count). Fit a
**Generalized Pareto Distribution** to the residual **exceedances over a high
threshold** `u` (POT), and in each resampled residual vector replace every
component's *excess over `u`* with a fresh GPD draw. Below `u`, values are untouched.

Specifics:

- **Exceedance *frequency* stays empirical, only the *magnitude* becomes
  parametric.** A resampled component exceeds `u` at the empirical rate (~5% at the
  95th-percentile threshold); the splice redraws the excess of those, so the tail can
  exceed history while the body and the exceedance rate are unchanged.
- **PWM, not MLE.** The GPD is fit by probability-weighted moments (Hosking & Wallis
  1987): closed-form, so the fit is pure-numpy, deterministic, and golden-testable,
  and more reliable than MLE below ~500 samples, which matches the short day-ahead
  residual history. No `scipy` dependency (consistent with R2.2's numpy-only reducer).
- **Upper tail first.** The decision-relevant spike for storage is the upside
  (discharge into scarcity); the lower (negative-price) tail is a symmetric extension
  left for later, with `TailModel.side` leaving room for it.
- **Opt-in.** `generate_scenarios(..., tail=None)` is byte-identical to R2.2; the tail
  draws come from the same RNG *after* the resample indices, so the bootstrap is
  unchanged when a tail is present but no component exceeds `u`.

## Consequences

- Scenarios can price an unprecedented spike, so the R2.3 CVaR tail is no longer
  capped at history. Measured live (NL 2024, held-out days): the fraction of realized
  prices above the scenario set's support ceiling falls from **7.4% (capped
  bootstrap) to 1.0% (GPD tail)**.
- Reduction interaction, measured, not assumed: forward-selection reduction **keeps**
  the tail (extreme paths sit far from the mass, so dropping one costs Kantorovich
  distance). No tail quota is needed; a property test guards this.
- The body 99th-percentile coverage is dominated by the point-forecast error, not the
  tail, so the honest calibration metric is the **support ceiling** (where the cap
  actually bites), not a body quantile. The gate reflects this.

## Failure mode

A too-heavy fitted `ξ` produces absurd draws (the demo saw a 100k€ path at ξ≈0.7 on
over-injected synthetic spikes); real price-residual fits sit at ξ≈0.1–0.3. Guarded
by: the un-capping / tail-heaviness property tests, the support-ceiling live gate
(a degenerate tail would over-cover), and the PWM fit requiring ≥2 exceedances.

## Alternatives considered

- **Replace the generator with a fully parametric tail model.** Rejected: discards
  the empirical intra-day shape the bootstrap preserves, for no gain in the body.
- **Add separate synthetic extreme scenarios with their own probabilities.**
  Rejected: changes the probability structure and scenario count, and needs a rule for
  the added mass; the in-place splice keeps `n` equiprobable atoms.
- **Block-maxima / GEV.** Rejected: wastes the sub-maximal exceedances POT uses, on an
  already-short residual history (Coles 2001, ch. 4).
- **Ad-hoc spike multiplier** (scale the worst historical residual). Rejected: no
  calibration, no return-level meaning.
- **Conditional GPD (parameters as a function of residual load).** The richer target
  R2.1c unblocks, deferred as future work (data-hungry: extremes are rare, and
  splitting by covariate makes them rarer).
