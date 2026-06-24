# ADR-0009: SoC expressed per-unit in config, absolute MWh in the model

**Status:** Accepted
**Date:** 2026-06-24

## Context

`docs/conventions.md` §2 (a locked contract) states that state of charge is
"MWh (absolute) in the model; per-unit only in config." When the R1.1 spec and
`BatterySpec` were first written, the SoC fields (`soc_min`, `soc_initial`,
`soc_terminal`) were given in absolute MWh — contradicting the convention. The
inconsistency was invisible because the default asset is 1 MWh, where the
per-unit fraction and the MWh value coincide numerically (`0.0`, `1.0`).

Two ways to resolve it: (a) make config per-unit, matching the convention; or
(b) amend the convention to permit absolute MWh in config.

## Decision

Config SoC is **per-unit** (a fraction of `capacity`, in `[soc_min, 1.0]`),
matching the locked convention. `capacity` stays MWh; power stays MW. The
`Battery` asset converts at registration —
`e_min = soc_min · capacity`, `e_0 = soc_initial · capacity`,
`e_tgt = soc_terminal · capacity`, `e_max = capacity` — and the model plus
`Schedule.soc` remain in absolute MWh.

## Consequences

- **Easier:** specs are size-independent. "Start at 50%" is `soc_initial = 0.5`
  for any asset size; changing `capacity` does not require rescaling the SoC
  bounds. Reusable across the 1-hour R1.1 asset and any 2-hour asset a later
  backtest (R1.4) targets.
- **Harder:** one conversion step at the asset boundary, and config values are
  no longer directly comparable to the MWh-valued model variables / outputs.
- **Enforced by:** the golden oracles and property tests in `tests/` (which now
  convert per-unit config to MWh before asserting), plus Pydantic field bounds
  (`soc_* ∈ [0, 1]`) and the cross-field validator (`soc_min < 1.0`,
  `soc_initial, soc_terminal ∈ [soc_min, 1.0]`).

## Failure mode

Someone passes an absolute MWh value (e.g. `soc_initial = 2.0` for a 5 MWh
asset) expecting "2 MWh" and silently gets rejected (`> 1.0`) — or, worse, a
future field accepts a value in `[0, 1]` that was meant as MWh. Signal: a
`ValidationError` at construction, or a backtest whose SoC trajectory is a
fraction of what was intended. Mitigation: per-unit is documented in the field
descriptions, the spec parameter table, and conventions §2.

## Alternatives considered

- **Absolute MWh in config (amend the convention).** Simpler — no conversion,
  config matches the model directly. Rejected: it couples every SoC field to
  `capacity`, is error-prone across asset sizes, and would weaken a deliberate
  locked decision for marginal convenience. The roadmap (degradation in cycles,
  a possible 2-hour backtest asset) favours size-independent config.
