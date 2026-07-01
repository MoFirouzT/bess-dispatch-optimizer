# ADR-0014: Conformalized quantile regression (CQR) over split conformal as the forecaster default

**Status:** Accepted
**Date:** 2026-07-01
**Supersedes / Superseded by:** —

## Context

R2.1 outputs calibrated day-ahead price *intervals* (spec `docs/specs/R2.1-forecaster.md`).
Two conformal constructions are available in MAPIE 1.x:

- **Split conformal** — one point model plus a single conformity quantile, giving a
  **constant-width** interval added symmetrically around the point forecast.
- **Conformalized quantile regression (CQR)** — lower/upper quantile models,
  conformalized, giving an **input-adaptive** interval width.

Both achieve the same *marginal* coverage guarantee. They differ in *conditional*
calibration.

## Decision

Default to **CQR**; keep split conformal as the baseline the coverage gate compares
against.

Day-ahead prices are strongly heteroscedastic: evening-peak and scarcity hours are
far more volatile than overnight hours. A constant-width interval is therefore
*conditionally* miscalibrated even when marginally correct — too wide at night, too
narrow at the peak. CQR widens where the market is uncertain and tightens where it is
calm, which is the honest uncertainty signal the stochastic layer (R2.2+) should
sample from.

**Implementation contract (verified this session, `mapie==1.4.1` / `lightgbm==4.6.0`):**
MAPIE 1.x CQR will not accept a single LightGBM (it cannot set the quantile
parameter), so pass **three prefit LGBM quantile models in order `[lower(α/2),
upper(1−α/2), median]`** with `prefit=True`, then `.conformalize(X_cal, y_cal)` and
`.predict_interval(X)`.

## Consequences

- Three base models to fit and persist instead of one; more compute, but the day-ahead
  problem is small.
- The coverage gate compares CQR against split conformal on the same walk-forward, so
  the adaptivity claim is measured, not asserted.
- Marginal coverage is all conformal guarantees — CQR does not promise *conditional*
  coverage, only better-calibrated width in practice. Enforced by the coverage gate
  (empirical ∈ [0.85, 0.95] at nominal 0.9) plus the interval-ordering property test.

## Failure mode

If the two quantile models cross (lower > upper before conformalization — MAPIE logs
"ill-sorted"), the interval is degenerate. Signal: the interval-ordering property test
(`lower ≤ point ≤ upper`) fails; CQR's correction and a monotone-in-confidence test
guard it.

## Alternatives considered

- **Split conformal as the default.** Rejected as default (kept as baseline): constant
  width is conditionally miscalibrated on heteroscedastic prices, which is the whole
  point of forecasting *uncertainty* here.
- **Bare LightGBM quantiles, no conformal.** Rejected: quantile regression has no
  finite-sample coverage guarantee; conformal is the distribution-free wrapper that
  makes the interval honest.
- **Bootstrap / Gaussian residual intervals.** Rejected: distribution-assuming and
  heavier than distribution-free conformal.
