# The scenario tail: a semiparametric GPD splice, conditioned through the scale

**Status:** Accepted
**Date:** 2026-07-24

*Consolidated on 2026-07-28 from two records: the decision to splice an extreme-value
tail onto the bootstrap, and the decision about which channel carries the conditioning.
The second only makes sense given the first, and they share their context.*

## Context

The residual-path bootstrap ([residual-path bootstrap](residual-path-bootstrap.md))
generates price scenarios by resampling whole-day forecast-error vectors. It preserves
intra-day correlation but is **bounded above by history**: the largest spike any
scenario can contain is the historical-maximum residual, so the risk-aware program and
its CVaR tail are blind to any spike larger than the calibration window has seen.

Fixing that raises two questions in sequence. How to add a tail at all, given three
options: replace the generator with a parametric model, add separate synthetic extreme
scenarios, or splice a parametric tail onto the existing empirical draws. And then,
since a price spike is a scarcity event driven by residual load, which channel should
carry that conditioning: the **magnitude** of spikes (the GPD scale) or their
**frequency** (the exceedance rate).

## Decision

### A semiparametric splice, in place

Keep the empirical whole-day bootstrap for the body (intra-day shape, equiprobable
atoms, same scenario count). Fit a **Generalized Pareto Distribution** to the residual
**exceedances over a high threshold** `u`, and in each resampled residual vector
replace every component's *excess over `u`* with a fresh GPD draw. Below `u`, values
are untouched.

- **Exceedance frequency stays empirical; only magnitude becomes parametric.** A
  component exceeds `u` at the empirical rate (~5% at a 95th-percentile threshold), and
  the splice redraws the excess of those, so the tail can exceed history while the body
  and the exceedance rate are unchanged.
- **Probability-weighted moments, not maximum likelihood.** The PWM fit is closed-form,
  so it is pure-numpy, deterministic, and golden-testable, and it is more reliable than
  MLE below roughly 500 samples, which is the regime a short day-ahead residual history
  sits in. No new dependency.
- **Upper tail first.** The decision-relevant spike for storage is the upside; the
  negative-price tail is a symmetric extension left for later, with room in the
  interface for it.
- **Opt-in.** With no tail the generator is byte-identical to the plain bootstrap, and
  tail draws come from the same RNG *after* the resample indices, so the bootstrap is
  unchanged when a tail is present but nothing exceeds `u`.

### Conditioned through the scale

**`β(x) = β₀·exp(γ·z)`**, a log-link on the standardized residual load, with the shape
and base scale reused from the unconditional fit. Fit the slope by ordinary least
squares of log-excess on the covariate, clamped non-negative. The frequency channel is
deferred.

## Rationale

**The splice preserves what the bootstrap is good at.** A fully parametric generator
would discard the empirical intra-day shape for no gain in the body, and separate
synthetic extreme scenarios would change the probability structure and scenario count.

**The scale channel has a clean exact identity.** A zero slope, or no covariate, is
byte-identical to the unconditional tail, so conditioning is a strict opt-in extension
of an already-green phase. The frequency channel has no such identity: it decouples
spike *location* from the bootstrap and needs a separate rate model.

**It stays closed-form and testable.** The OLS log-link slope needs no optimizer, where
a rate model would, and estimating an exceedance probability per covariate value splits
already-rare exceedances further.

**The non-negativity clamp encodes a prior**: a spike tail should not get *lighter* on
tighter hours. A negative raw slope is almost surely overfitting on thin extreme data,
so it is clamped and flagged, never shipped.

## Consequences

- Scenarios can price an unprecedented spike, so the CVaR tail is no longer capped at
  history. Measured on real NL held-out days, the fraction of realized prices above the
  scenario set's support ceiling falls from **7.4% to 1.0%**.
- Measured on the same data, the fitted slope is genuinely positive (`γ ≈ 0.21`): the
  tail scale rises from `β ≈ 6.2` on slack hours to `β ≈ 10.4` on tight hours, about
  **69%**, so spikes are larger where they physically occur and the program's
  reservation concentrates there rather than uniformly.
- Reduction interaction, measured rather than assumed: forward selection **keeps** the
  tail, because extreme paths sit far from the mass so dropping one costs Kantorovich
  distance. No tail quota is needed, and a property test guards it.
- The body's high quantiles are dominated by point-forecast error rather than by the
  tail, so the honest calibration metric is the **support ceiling**, where the cap
  actually bites, not a body quantile.
- An asset or window with no residual-load signal fits a near-zero slope and reduces to
  the unconditional tail, reported as a null rather than a failure.

## Failure mode

**A too-heavy fitted shape parameter produces absurd draws.** A demo on over-injected
synthetic spikes reached a six-figure path at `ξ ≈ 0.7`; real price-residual fits sit at
`ξ ≈ 0.1` to `0.3`, which is the range to expect and the signal that a fit has gone wrong.
Guarded by the tail-heaviness property tests, the support-ceiling live gate (a degenerate
tail would over-cover), and a minimum of two exceedances for the fit.

**Over-fitting the conditioning slope** on thin exceedances is guarded by the clamp, by
a no-signal property test that recovers a near-zero slope when the covariate is noise,
and by the live gate reporting the slope with provenance.

## Alternatives considered

- **Replace the generator with a fully parametric tail model.** Rejected: discards the
  empirical intra-day shape for no gain in the body.
- **Add separate synthetic extreme scenarios.** Rejected: changes the probability
  structure and scenario count, and needs a rule for the added mass.
- **Block-maxima / GEV.** Rejected: wastes the sub-maximal exceedances that a
  peaks-over-threshold fit uses, on an already-short history.
- **An ad-hoc spike multiplier.** Rejected: no calibration and no return-level meaning.
- **The frequency channel**, or **both channels**. Deferred: more decision-relevant,
  since frequency predicts spike *timing*, but a larger redesign with no clean identity
  and a data-hungry rate model. Revisit once the magnitude channel has earned it.
  *(Later measurement made this moot: the tail-value study found no dispatch value in
  the tail at any recourse budget, so further refinement was stopped.)*
- **A covariate fit on both GPD parameters.** The textbook non-stationary form, but it
  reintroduces a numerical optimizer and is unstable for the shape parameter.
