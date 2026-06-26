# ADR-0011: Circuit-breaker semantics for the dispatch endpoint

**Status:** Accepted
**Date:** 2026-06-26
**Supersedes / Superseded by:** —

## Context

R1.5 serves dispatch over HTTP. Two things can go wrong, and they are *not* the
same kind of wrong:

1. The **input** is invalid or provably infeasible (empty horizon, non-finite
   price, non-positive `dt`, unreachable terminal SoC). Pre-flight (R1.3) already
   detects these as structured `ValidationIssue`s. No schedule, greedy or optimal,
   can repair a bad request.
2. The **input is valid** but the solver does not deliver a proven optimum inside
   the latency budget (HiGHS hits its `time_limit`, returns a non-optimal status,
   or raises). A dispatch decision is still needed.

Conflating these would either hide bad input behind a silent fallback, or fail a
serviceable request with a 5xx.

## Decision

Split the two classes:

- **Invalid input → HTTP 422**, body = the `ValidationIssue` list (code, field,
  message, context). No fallback. The client must fix the request.
- **Valid input, no optimum in budget → HTTP 200** with the **greedy** schedule,
  `mode="fallback_greedy"`, and a logged fallback event. A feasible dispatch is
  always served for a valid request.
- **Valid input, optimum in budget → HTTP 200**, `mode="optimal"`.

The budget is enforced twice: HiGHS `time_limit` (the solver stops itself) and a
wall-clock guard in the breaker (covers model build + solution load). Default
budget **2.0 s** (app setting, env-overridable).

The breaker is a pure function `dispatch(request, *, budget, solve_fn, greedy_fn)`
with injectable `solve_fn`/`greedy_fn`, so tests force each branch deterministically
without patching globals.

## Consequences

- Clients get a machine-readable 422 for their own errors and a served (if
  suboptimal) schedule for solver stress — graceful degradation, not an outage.
- The fallback is the R1.4 greedy baseline, which is **feasibility-preserving and
  ends empty**, so a served fallback schedule satisfies the same physical
  invariants as an optimal one. Enforced by the R1.5 feasibility property test
  (runs against the response in both modes).
- Structured typed errors cross the API boundary, never raw solver traces
  (conventions §6).

## Failure mode

A solver failure that is *miscategorized* as invalid input (422) would wrongly
deny a serviceable request; the inverse (invalid input silently served as greedy)
would emit a dispatch for nonsense data. Signal: the breaker property test
(forced `solve_fn` failure on valid input must return 200 greedy) and the 422
oracle (empty horizon must be 422, never a fallback) pin both directions.

## Alternatives considered

- **Always 200, greedy on any error.** Rejected: masks invalid input, emitting a
  dispatch for data that should be rejected.
- **Always 5xx on solver failure.** Rejected: defeats the purpose of the phase —
  the system should keep dispatching under solver stress.
- **Retry the solve with relaxed settings before falling back.** Deferred: warm
  starts and re-solve tuning are an R2.3 latency concern, out of scope here.
