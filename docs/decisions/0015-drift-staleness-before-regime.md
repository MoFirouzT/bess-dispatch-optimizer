# ADR-0015: Drift classification checks staleness (vs. a naive baseline) before regime shift

**Status:** Accepted
**Date:** 2026-07-01
**Supersedes / Superseded by:** —

## Context

R2.1b monitors the forecaster and must classify degradation as either a **regime
shift** (the market changed) or **model staleness** (this model decayed). Two signals
are available over the trailing window: the input-distribution stability (PSI) and the
forecaster's error *relative to a seasonal-naive baseline* (`error_ratio =
forecaster_MAE / naive_MAE`). When both a distribution shift *and* elevated relative
error occur together, the classifier needs a deterministic precedence.

## Decision

Check **staleness first**: if `error_ratio ≥ staleness_ratio` (default 1.3), classify
`STALENESS`; else if `psi ≥ psi_warn` (default 0.2), classify `REGIME_SHIFT`; else
`HEALTHY`.

The rationale is the load-bearing insight of the phase: **even under a genuine regime
shift, a healthy model should degrade no worse than a naive baseline.** A seasonal-
naive forecast ("same hour last week") sees the same shifted world; if the ML model is
*materially worse than naive*, that is model-specific decay, not the world's fault, and
the action is *retrain*. Only when the model is still competitive with naive but inputs
have moved do we call it a regime shift, where the action is *recalibrate / accept*.

## Consequences

- The two flags map to different operator actions (retrain vs. recalibrate), so the
  classification is actionable, not just descriptive.
- Attribution is robust to the ambiguous "both fired" case, which is common in practice
  (a regime shift often inflates absolute error for everything).
- Enforced by the discrimination gate: an injected regime shift (level jump, both model
  and naive wrong ⇒ ratio ≈ 1, PSI high) and an injected staleness pattern (inputs
  stable, model worse than naive ⇒ ratio high) must classify differently and correctly.

## Failure mode

A poor naive baseline breaks the logic: if the naive is too weak (e.g. `season = 24`
ignoring weekend structure), a model that is actually fine looks "stale" against a bad
benchmark and vice versa. Signal: the discrimination gate, plus using a seasonal-naive
at `season = 168 h` (weekly) so the benchmark itself respects weekday/weekend structure.

## Alternatives considered

- **Regime shift first (PSI before ratio).** Rejected: a stale model during a quiet
  market (low PSI) would be missed, and a stale model during a shift would be
  mislabeled "regime shift", hiding that it needs retraining.
- **A single blended score.** Rejected: collapsing two distinct causes into one number
  loses the retrain-vs-recalibrate distinction that is the entire point.
- **Absolute error threshold, no baseline.** Rejected: an absolute MAE threshold cannot
  separate "the world got harder" from "my model got worse" — only a *relative* (vs.
  naive) comparison can.
