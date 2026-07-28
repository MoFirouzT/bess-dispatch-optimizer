# Two circuit breakers, two taxonomies, one shared degradation vocabulary

**Status:** Accepted
**Date:** 2026-07-01

*Consolidated on 2026-07-28 from two records: the decision to keep the ingestion
breaker separate from the solver breaker, and the decision to give the two a shared
vocabulary so they compose. The second is a rider on the first.*

## Context

The serving path already had a circuit breaker around the **solve**: valid input
where the solver misses its latency budget falls back to the greedy schedule
([dispatch circuit breaker](dispatch-circuit-breaker.md)). The data feed is a second
failure surface. A market-data feed can time out, return a 5xx, or, worse, return
present-but-corrupt data: a stuck feed, a gap in the expected grid, a duplicate
timestamp, a non-finite value, an implausible out-of-band price.

A dispatch computed on silently-bad prices is the failure mode this kind of platform
is most exposed to, and **a stale-but-present price is more dangerous than an obvious
outage, because it fails silently.**

Two questions follow. Whether to reuse one generic breaker wrapping both fetch and
solve, or build a second with its own taxonomy. And then, given two breakers, how a
consumer learns that a schedule was produced along a chain that degraded at *either*
stage: the guard may have fallen back to stale cached prices while the solver returned
a proven optimum on them, and reported independently those two flags let a consumer
read `mode="optimal"` and conclude all is well.

There is also a boundary to draw against pre-flight validation, which already inspects
optimization inputs, since a reader will reasonably ask whether this is the same thing.

## Decision

**Two distinct breakers, two taxonomies.** The solver breaker reports
`mode ∈ {optimal, fallback_greedy}`. The ingestion breaker
(`bess.data.ingestion_guard`) reports `status ∈ {healthy, outage, anomaly}`, wraps the
*fetch*, and on either failure class falls back to the last-known-good cached series
and logs the specific check that fired.

**One shared vocabulary, so they compose rather than report in isolation.** The guard
emits a small frozen value object, `GuardResult`, in the `data` leaf. Where a fetch
feeds a solve, the consumer composes `GuardResult.status` with the solver `mode` into
one honest provenance statement: **a solve on degraded data is surfaced as degraded,
regardless of the solver mode.**

**The pre-flight boundary,** stated so it is deliberate rather than accidental overlap:

- **Pre-flight validation** answers *is this problem solvable*: structural and
  physical feasibility of the optimization inputs. It runs on a well-formed request.
- **The ingestion guard** answers *can this data be trusted*: provenance and integrity
  of the fetched series, before it ever becomes an optimization input. It runs on the
  wire.

They do not overlap. A series can pass the guard yet fail pre-flight (trustworthy but
infeasible), or fail the guard while being structurally solvable.

**Scope honesty:** the dispatch endpoint takes client-supplied prices and does not
fetch, so this adds no fetch-inside-the-endpoint. The composition is exercised on the
backtest and example fetch-then-solve path, and the vocabulary is defined so a future
auto-fetch endpoint can attach a data status next to `mode` without new plumbing.

## Consequences

- Outage and anomaly are distinguishable in the logs, so an on-call engineer sees
  *which layer* failed rather than one undifferentiated "degraded" event.
- A single place to answer "how much do I trust this schedule?", spanning both data
  and solver health, instead of two disconnected flags a caller must cross-check.
- More code and two taxonomies to maintain: the accepted cost of not conflating "the
  data was bad" with "the solver was slow".
- `bess.data` stays a **leaf**. The guard imports nothing else in `bess`; consumers
  read its result and it never reaches upward. `GuardResult` is a leaf-local value
  object, read the way the serving layer already reads a `Schedule`, so no new import
  edge is created and the leaf contract holds.
- Enforced by golden oracles (a feed frozen at an arbitrary price, and a known gap,
  must be caught and correctly labelled), a property test (no corrupted series ever
  classifies healthy, and no false positive on legitimate zeros or negatives), and an
  end-to-end test that a solve on a substituted last-known-good series reports
  degraded provenance rather than a bare optimal.

  The stuck-feed check keys on the *price*, not the run length: a bit-identical run at
  a structural focal point is market behaviour, not a freeze, so **a stuck-zero block
  must classify healthy**. Real NL and BE both cleared at €0.00 for eight consecutive
  hours on 2024-03-24.

## Failure mode

A **shared** breaker firing on data corruption looks identical in the logs to a slow
solver, which is the ambiguity that costs a debugging afternoon during an incident.

Conversely, if the pre-flight boundary blurs, the guard might duplicate feasibility
checks, or let a structural fault reach the solver on the assumption that pre-flight
owns it. The signal that keeps them honest: the guard classifies *data pathology* only
and defers every feasibility judgment, verified by tests that a
trustworthy-but-infeasible series passes the guard and is rejected by pre-flight, and
the reverse.

A third risk is that consumers ignore the guard status and read only the solver mode,
in which case the shared vocabulary buys nothing and the silent-stale-dispatch hole
reopens. Signal: the composition test above. If it is ever weakened to assert on the
mode alone, the guarantee is gone.

## Alternatives considered

- **One generic breaker wrapping fetch and solve.** Rejected: a single degraded state
  hides whether the data or the solver failed, the one distinction an operator most
  needs mid-incident.
- **Fold the checks into the loader.** Rejected: burying the outage-versus-anomaly
  split inside the fetch function makes it a comment rather than a testable contract.
- **Extend pre-flight to cover data integrity.** Rejected: conflates two different
  questions with two different fallbacks (reject the request versus substitute
  last-known-good).
- **Each breaker logs independently, with no shared status.** Rejected: reproduces the
  silent-stale-dispatch hole, since optimal on stale data reads as fully healthy.
- **Merge both into one status enum.** Rejected: that is this decision in reverse. The
  taxonomies are deliberately distinct; they need to compose, not collapse.
- **Push provenance into the dispatch response now.** Deferred: the endpoint does not
  fetch, so there is no provenance to report there yet.
