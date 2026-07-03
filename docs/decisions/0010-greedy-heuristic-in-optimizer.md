# ADR-0010: Relocate the greedy heuristic to `bess.optimizer`

**Status:** Accepted
**Date:** 2026-06-26
**Supersedes / Superseded by:** None

## Context

R1.5 adds a serving layer (`bess.api`) whose circuit breaker must produce a
**greedy** schedule when the solver fails or exceeds its latency budget. The
greedy heuristic (`greedy_window` + its `_trajectory`/`_liquidate` helpers)
currently lives in `bess.backtest.baselines`.

`backtest` is, by an import-linter contract, an **offline tool** that must not
import the serving chain; and symmetrically, the serving chain should not depend
on an offline analysis harness to handle a live request. The greedy rule itself
is not a backtest concept; it is an alternative *dispatch strategy* over the same
asset and horizon as `solve()`.

## Decision

Move `greedy_window` and its helpers to a new module `bess.optimizer.heuristics`.
`bess.backtest.baselines` imports `greedy_window` from there (re-exporting for its
existing callers). `bess.api` imports it from there too.

## Consequences

- Both `api → optimizer` and `backtest → optimizer` are already-allowed layer
  edges, so no import-linter contract is widened; the 4 existing contracts stay
  KEPT. Enforced mechanically by `uv run lint-imports`.
- The greedy schedule is computed identically (pure code move), so the R1.4
  golden/property gates for greedy values are unchanged and serve as the
  regression check for the move.
- `optimizer` now owns two dispatch strategies (exact MILP + greedy heuristic),
  which is a coherent home: both are functions of `(prices, spec, dt)` returning a
  `Schedule`.

## Failure mode

A future edit could reintroduce a `backtest`-specific dependency into the greedy
helper, coupling the serving fallback to the offline harness. Signal: an
import-linter break, or `bess.api` transitively importing `bess.backtest`.

## Alternatives considered

- **Leave greedy in `backtest`, let `api` import `backtest`.** Rejected: makes the
  live serving path depend on the offline analysis tool, the exact coupling the
  offline-tool contract exists to prevent.
- **Duplicate the greedy logic in `api`.** Rejected: two copies of a
  feasibility-preserving heuristic drift apart; the R1.4 gates would no longer
  cover the served fallback.
