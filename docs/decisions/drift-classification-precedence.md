# Drift classification: staleness, then regime, then miscalibration

**Status:** Accepted
**Date:** 2026-07-01, extended 2026-07-03

*Consolidated on 2026-07-28 from two records: the original two-state precedence and
the amendment that added coverage as a third state. The amendment only reordered and
extended the same rule, so they are one decision.*

## Context

The drift monitor watches the price forecaster and must say **why** it degraded, not
merely that it did, because the answer determines the remedy. Three signals are
available over a trailing window: the forecaster's error relative to a seasonal-naive
baseline (`error_ratio`), the input-distribution stability (PSI), and the empirical
coverage of its intervals.

When more than one fires, the classifier needs a deterministic precedence. Getting
that order wrong turns an actionable alarm back into "accuracy dropped".

## Decision

Classify in this order, first match winning:

1. `error_ratio >= staleness_ratio` (default 1.3) → **STALENESS**, so retrain
2. else `psi >= psi_warn` (default 0.2) → **REGIME_SHIFT**, so wait or accept
3. else `coverage <= confidence_level - coverage_tol`, with
   `n_coverage >= min_coverage_samples` → **MISCALIBRATION**, so recalibrate
4. else **HEALTHY**

Defaults: `coverage_tol = 0.10`, `min_coverage_samples = 100`. Coverage is
**one-sided**: only under-coverage alarms. Over-wide intervals are reported as a
signed deviation, because they are inefficient rather than unsafe.

## Rationale

**Staleness wins over everything**, and this is the load-bearing insight: *even under
a genuine regime shift, a healthy model should degrade no worse than a naive
baseline.* A seasonal-naive forecast sees the same shifted world. If the model is
materially worse than naive, that is model-specific decay, not the world's fault, and
the action is retrain.

**Miscalibration is checked after regime, deliberately.** A genuine regime shift also
breaks coverage, so ordering regime first preserves the "market moved" attribution
instead of relabelling it a calibration problem. Miscalibration is reserved for its
clean case: the point model tracks, inputs are stable, and the intervals still
under-cover, meaning the conformal layer specifically decayed.

**Coverage had to become a state at all** because the monitor originally computed it
and then ignored it. The forecaster's actual product is a *calibrated interval*, and
decalibration is orthogonal to the other two signals: a model can hold
`error_ratio ≈ 1` at low PSI while its 90% band silently covers 75%. That gap
propagated straight into scenario generation, which samples from these intervals, so a
miscalibrated band quietly corrupted the stochastic layer's risk handling.

## Consequences

- The three non-healthy states map to three distinct operator actions: retrain,
  wait, recalibrate. The classification is actionable rather than descriptive.
- Attribution is robust to the common "both fired" case, since a regime shift often
  inflates absolute error for everything.
- Enforced by discrimination gates: an injected regime shift (level jump, both model
  and naive wrong, so ratio ≈ 1 at high PSI) and an injected staleness pattern
  (inputs stable, model worse than naive) must classify differently and correctly;
  and an episode with a tracking point model, stable inputs, and too-tight bands must
  classify MISCALIBRATION, while the same episode with correctly wide bands must
  classify HEALTHY.

## Failure mode

**A poor naive baseline breaks the logic.** If the benchmark is too weak (for example
a 24-hour season that ignores weekend structure), a healthy model looks stale against
it, and the reverse. Mitigated by using a weekly (168 h) seasonal-naive so the
benchmark respects weekday and weekend structure.

**Small, noisy windows break the coverage check.** Empirical coverage over a short
window is high-variance: a 90% band over 24 points expects ~2.4 misses, and binomial
noise around that is large, so a naive threshold cries wolf. Guarded by
`min_coverage_samples`, below which coverage stays informational.

## Alternatives considered

- **Regime shift first.** Rejected: a stale model in a quiet market would be missed,
  and a stale model during a shift would be mislabelled "regime shift", hiding that
  it needs retraining.
- **Miscalibration before regime.** Rejected for the mirror reason: it would relabel a
  regime shift, which also under-covers, as a calibration issue. Recalibration only
  makes sense when inputs are stable, which the post-regime ordering guarantees.
- **A single blended score**, or folding coverage into the error ratio. Rejected:
  collapsing distinct causes into one number destroys the retrain-versus-recalibrate
  distinction that is the entire point.
- **An absolute error threshold with no baseline.** Rejected: it cannot separate "the
  world got harder" from "my model got worse". Only a relative comparison can.
- **A two-sided coverage flag.** Rejected: over-wide intervals are inefficient, not a
  reliability risk.
- **A one-sided binomial test on the miss count.** More principled on small windows,
  but more machinery than a monitoring phase warrants. Revisit if real windows prove
  the fixed band too blunt.
