# ADR-0026: Condition the scenario tail through the GPD scale (magnitude), not the exceedance rate

**Status:** Accepted
**Date:** 2026-07-24
**Supersedes / Superseded by:** None

## Context

R2.2b ([ADR-0025](0025-semiparametric-gpd-scenario-tail.md)) added an unconditional
GPD tail to the scenario bootstrap, applied uniformly to every hour of every
scenario. But a price spike is a residual-load-extreme event, so the tail should be
*conditioned* on residual load, the covariate R2.1c added. R2.2c (spec
`docs/specs/R2.2c-conditional-tail.md`) does this. There are two channels through
which residual load `x` can drive the tail:

- **Magnitude:** the GPD scale `β(x)` (how big spikes are when they happen).
- **Frequency:** the exceedance rate `λ(x)` (how often hours spike).

## Decision

**Condition the magnitude: `β(x) = β₀·exp(γ·z)`**, a log-link on the standardized
residual load `z`, with `ξ` and `β₀` reused from R2.2b's unconditional PWM fit (`β₀`
is the scale at `z = 0`). Fit `γ` by OLS of `log(excess)` on `z`, clamped `γ ≥ 0`.
The frequency channel `λ(x)` is deferred to R2.2d.

Confirmed with the human as the phase's one design fork.

Rationale:

- **Clean, exact identity.** `γ = 0` (or no covariate) is byte-identical to R2.2b, so
  the conditioning is a strict, opt-in extension of a green phase. The frequency
  channel has no such identity: it decouples spike *location* from the bootstrap and
  needs a separate rate model, a larger redesign.
- **Pure-numpy, golden-testable.** The OLS log-link slope is closed-form (no MLE, no
  `scipy`); the frequency channel's rate model is not, and is more data-hungry
  (estimating `P(exceed | x)` splits already-rare exceedances by covariate).
- **Decision-relevant.** Both channels shift the R2.3 CVaR reservation toward
  tight-margin hours; magnitude does so through spike *size*, which is enough to earn
  the phase. The `γ ≥ 0` clamp encodes the prior that a spike tail should not get
  *lighter* on tighter hours (almost surely overfitting on thin extreme data).

## Consequences

- Measured on real NL 2024 (held-out mean-day-shape residuals, residual-load
  covariate): `γ ≈ 0.21 > 0`, so residual load genuinely predicts spike magnitude on
  this asset; the tail scale rises from `β ≈ 6.2` on slack hours (10th-pct residual
  load) to `β ≈ 10.4` on tight hours (90th-pct), about **+69%**.
- The scenario generator's spikes are now larger on high-residual-load hours, so the
  two-stage program's tail risk (and SoC reservation) concentrates where spikes
  actually occur, rather than uniformly.
- A future asset/window with no residual-load signal fits `γ ≈ 0` and reduces to
  R2.2b, reported as a null (the R2.5 / R2.1c honesty rule), not a failure.

## Failure mode

Over-fitting `γ` on thin exceedances (spuriously heavy tails on tight hours) is
guarded by the `γ ≥ 0` clamp, the no-signal property test (`γ ≈ 0` when the covariate
is noise), and the live gate reporting `γ` with provenance. A negative raw slope
(spikes lighter on tighter hours) is clamped and flagged, never shipped.

## Alternatives considered

- **Frequency channel `λ(x)`.** Deferred to R2.2d: more decision-relevant (predicts
  spike *timing*) but a larger redesign with no clean R2.2b identity and a data-hungry
  rate model.
- **Both channels.** Rejected for R2.2c: biggest build, hardest to calibrate and test
  on thin extreme data; revisit once the magnitude channel is proven.
- **Covariate-MLE GPD (`ξ(x)` and `β(x)`).** The textbook non-stationary fit (Coles
  2001, ch. 6) but reintroduces an optimizer/`scipy` and is unstable for `ξ(x)`.
  Rejected for the scale-only log-link.
