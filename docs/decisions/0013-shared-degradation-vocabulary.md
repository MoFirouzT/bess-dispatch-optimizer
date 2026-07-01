# ADR-0013: One shared degradation vocabulary across the two circuit breakers

**Status:** Accepted
**Date:** 2026-07-01
**Supersedes / Superseded by:** —

## Context

With two breakers in play (ADR-0012), a schedule can be produced along a chain that
degraded at *either* stage: the ingestion guard may have fallen back to stale cached
prices (`status="anomaly"`), and the solver may then return a proven optimum on that
stale data (`mode="optimal"`). Reported independently, the two flags let a downstream
consumer read `mode="optimal"` and conclude the result is fully healthy — the exact
silent-stale-dispatch hole the ingestion guard exists to close. A dispatch is only as
trustworthy as the price it was computed from.

`bess.data` is a leaf (import-linter); it cannot import the api/backtest layers, so
any shared status must be a value the guard *produces* and consumers *read*, never an
upward import.

## Decision

Define one degradation vocabulary and let the two breakers compose rather than report
in isolation.

- Ingestion guard emits a small frozen value object, `GuardResult`, in the `data`
  leaf: `{status: healthy|outage|anomaly, prices, reason, degraded}`.
- Where a fetch feeds a solve (the backtest, a batch pipeline, a future auto-fetch
  serving path), the consumer composes `GuardResult.status` with the solver `mode`
  into one honest provenance statement. A solve on degraded data is surfaced as
  degraded, regardless of the solver `mode`.

**Scope honesty:** R1.5's `POST /dispatch` takes client-supplied prices and does not
fetch (its out-of-scope, unchanged). So this ADR does not add fetch-inside-the-
endpoint. The composition is exercised on the backtest/example fetch→solve path, and
the vocabulary is defined so a future auto-fetch endpoint can attach `data_status`
next to `mode` without new plumbing.

## Consequences

- A single place to answer "how much do I trust this schedule?" spanning both data
  and solver health, instead of two disconnected flags a caller must remember to
  cross-check.
- `GuardResult` is a leaf-local value object; consumers read it (as the api layer
  already reads `Schedule` from `optimizer`), so no new import edge is created and the
  "data is a leaf" contract stays KEPT.
- Enforced mechanically by an R1.5b acceptance-gate test: the backtest/example path
  routes through `guarded_fetch`, and a solve on a substituted last-known-good series
  reports a degraded provenance, not a bare `optimal`.

## Failure mode

If consumers ignore `GuardResult.status` and read only the solver `mode`, the shared
vocabulary buys nothing and the silent-stale-dispatch hole reopens. Signal: the
end-to-end composition test above; if it is ever weakened to assert on `mode` alone,
the guarantee is gone. A second risk is over-plumbing — trying to thread provenance
into the R1.5 endpoint that does not fetch — which the scope-honesty clause explicitly
forbids.

## Alternatives considered

- **Each breaker logs independently, no shared status.** Rejected: reproduces the
  silent-stale-dispatch hole — `optimal` on stale data reads as fully healthy.
- **Merge both breakers into one status enum.** Rejected: that is ADR-0012 in reverse;
  the taxonomies are deliberately distinct, they only need to *compose*, not collapse.
- **Push provenance into the R1.5 `/dispatch` response now.** Rejected/deferred: the
  endpoint takes client-supplied prices and does not fetch, so there is no data
  provenance to report there yet; revisit if an auto-fetch endpoint is added.
