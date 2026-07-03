# ADR-0016: Interval miscalibration is a distinct drift state, ordered after regime

**Status:** Accepted
**Date:** 2026-07-03
**Supersedes / Superseded by:** amends [ADR-0015](0015-drift-staleness-before-regime.md) (extends its precedence)

## Context

R2.1b's monitor originally classified degradation on two signals: error relative to a
seasonal-naive baseline (staleness) and input-distribution stability (PSI, regime). It
*computed* empirical interval coverage but never classified on it. Yet the R2.1
forecaster's product is *calibrated intervals* (its headline gate is empirical coverage
≈ nominal), and coverage decalibration is orthogonal to both existing signals: a model
can hold `error_ratio ≈ 1` and low PSI while its 90% band silently covers 75%. That
failure went undetected, and it propagates directly into R2.2, which samples scenarios
from these intervals, a miscalibrated band yields a wrong scenario set and quietly
corrupts the stochastic layer's risk handling.

## Decision

Add `DriftStatus.MISCALIBRATION` and extend ADR-0015's precedence to:

1. `error_ratio ≥ staleness_ratio` → **STALENESS** (retrain)
2. else `psi ≥ psi_warn` → **REGIME_SHIFT** (world moved)
3. else `coverage ≤ confidence_level − coverage_tol`, with `n_coverage ≥
   min_coverage_samples` → **MISCALIBRATION** (recalibrate the conformal layer)
4. else **HEALTHY**

Defaults: `coverage_tol = 0.10`, `min_coverage_samples = 100`. Coverage is **one-sided**:
only under-coverage flags; over-wide intervals are reported as a signed deviation but
never alarm.

## Rationale

- **Miscalibration is checked *after* regime, on purpose.** A genuine regime shift also
  breaks coverage; ordering regime first keeps the "market moved" attribution instead of
  mislabeling it a calibration problem. MISCALIBRATION is thus reserved for its clean
  case: point model tracks, inputs are stable, but the intervals under-cover, i.e. the
  conformal layer specifically decayed.
- **It maps to a distinct remedy.** The three non-healthy states now correspond to three
  actions; retrain (staleness), accept/adapt (regime), and **recalibrate** the conformal
  layer via the forecaster's existing `recalibrate()` (miscalibration). This preserves
  the retrain-vs-recalibrate actionability that motivated ADR-0015.
- **Staleness still wins over everything**, unchanged from ADR-0015: a model worse than
  naive is model-specific decay regardless of what coverage or PSI say.

## Consequences

- The monitor now watches the forecaster's actual guarantee, not just its point error;
  the gap that let miscalibrated intervals reach R2.2 is closed.
- Enforced by a new discrimination gate: an injected episode with a tracking point model,
  stable inputs (low PSI), and too-tight bands must classify `MISCALIBRATION`, while the
  same episode with correctly wide bands must classify `HEALTHY`.

## Failure mode

Small, noisy windows: empirical coverage over a short trailing window is high-variance
(a 90% band over 24 points expects ~2.4 misses, but binomial noise is large), so a naive
threshold would cry wolf. Guarded by `min_coverage_samples` (default 100), below which
coverage stays informational and never triggers a flag.

## Alternatives considered

- **Miscalibration before regime.** Rejected: it would relabel a regime shift (which also
  under-covers) as a calibration issue, hiding that the world moved. Recalibration only
  makes sense when inputs are stable, which the post-regime ordering guarantees.
- **Two-sided coverage flag.** Rejected: over-wide intervals are merely inefficient, not a
  reliability risk; reporting the signed deviation suffices without an alarm.
- **A one-sided binomial test on the miss count.** More principled on small windows, but
  more machinery than this monitoring phase warrants; the `min_coverage_samples` guard
  plus a fixed tolerance is the proportionate choice. Revisit if real ENTSO-E windows
  prove the fixed band too blunt.
- **Fold coverage into the error ratio.** Rejected: collapsing point accuracy and interval
  calibration into one number loses the retrain-vs-recalibrate distinction, the same
  reason ADR-0015 rejected a blended score.
