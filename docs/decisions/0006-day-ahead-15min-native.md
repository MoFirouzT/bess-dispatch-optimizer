# ADR-0006: Day-ahead is 15-minute native; the R1.1 hourly core is a deliberate simplification

**Status:** Accepted
**Date:** 2026-06-24 *(estimated; project foundation)*

*Back-filled (0001–0008); the date is the estimated inception date, not when this
file was written.*

## Context

The EU day-ahead market is 15-minute native (the SDAC market time unit moved to
15-minute resolution in 2025-10). A model hardcoded to hourly steps would be wrong
against the real market. But the R1.1 golden oracles are hand-derived, and
hand-verifying exact optima is far clearer at hourly resolution.

## Decision

Keep the model **resolution-agnostic**: `Δt` (`dt`) is a **per-solve argument**,
not a baked-in constant. The R1.1 core and its golden oracles use **hourly** `dt`
as a deliberate, documented simplification for hand-verifiable optima;
**quarter-hourly is handled at the data layer (R1.4)**, where the loader produces
15- or 60-minute series and the same model consumes them unchanged.

## Consequences

- **Easier:** golden values stay hand-checkable at hourly `dt`; the identical
  model serves 15-minute data with no formulation change. Survives the 15-minute
  switch.
- **Harder:** `dt` must be threaded through consistently; any per-period quantity
  (throughput, degradation, energy) has to scale with `dt`, not assume one hour.
- **Enforced by:** `dt` as a `solve()` argument; the R1.4b loader emitting 60/15-
  minute series; the drift monitor's wall-clock-hours framing
  ([ADR-0015](0015-drift-staleness-before-regime.md)) so thresholds survive the
  resolution change.

## Failure mode

A per-period constant silently assumes a 1-hour step and mis-scales under
15-minute data (e.g. energy = power × 1 instead of × `dt`). Signal: SoC or
throughput off by a 4× factor on quarter-hourly input. Mitigation: `dt` is
explicit everywhere; property tests exercise non-unit `dt`.

## Alternatives considered

- **Hardcode hourly.** Rejected: wrong against a 15-minute-native market; breaks at
  the 2025-10 switch.
- **15-minute-only oracles.** Rejected: exact optima are much harder to derive and
  hand-verify at quarter-hourly resolution; hourly oracles plus a resolution-
  agnostic `dt` give both correctness and checkability.
