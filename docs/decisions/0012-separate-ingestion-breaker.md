# ADR-0012: A separate ingestion circuit breaker from the solver circuit breaker

**Status:** Accepted
**Date:** 2026-07-01
**Supersedes / Superseded by:** None

## Context

R1.5 (ADR-0011) added a circuit breaker around the **solve**: valid input where the
solver misses the latency budget falls back to the greedy schedule. R1.5b adds a
second failure surface, the **fetch**. A market-data feed can time out, return a
5xx, or (worse) return present-but-corrupt data: a stuck/frozen feed, a gap in the
expected 24/96-slot grid, a duplicate timestamp, a non-finite value, or an
implausible out-of-band price. A dispatch computed on silently-bad prices is the
failure mode a shared, mission-critical optimization platform is most exposed to,
and a stale-but-present price is more dangerous than an obvious outage because it
fails silently.

The question is whether to reuse one generic breaker wrapping both fetch and solve,
or build a second, distinct breaker for ingestion with its own failure taxonomy.

There is also a boundary to draw against R1.3 pre-flight validation, which already
inspects optimization inputs, a reviewer will reasonably ask "isn't this the same
thing?"

## Decision

Two distinct breakers, two taxonomies.

- The **solver breaker** (R1.5) reports `mode ∈ {optimal, fallback_greedy}`.
- The **ingestion breaker** (R1.5b, `bess.data.ingestion_guard`) reports
  `status ∈ {healthy, outage, anomaly}`, wraps the *fetch*, and on either failure
  class falls back to the last-known-good cached series and logs the specific check
  that fired.

**The R1.3-vs-R1.5b line** (stated so it is deliberate, not accidental overlap):

- **R1.3 pre-flight** answers *is this problem solvable*: structural and physical
  feasibility of the optimization inputs (SoC window, inverter cap, horizon length).
  It runs on a well-formed request.
- **R1.5b ingestion guard** answers *can this data be trusted*: provenance and
  integrity of the fetched series, before it ever becomes an optimization input.
  It runs on the wire.

They do not overlap: a series can pass R1.5b (trustworthy) yet fail R1.3 (infeasible
battery window), or fail R1.5b (stuck feed) while being structurally solvable.

## Consequences

- Outage and anomaly are grep-distinguishable in the logs (`status` + `reason`
  fields), so an on-call engineer sees *which layer* failed rather than one
  undifferentiated "degraded" event.
- More code and two taxonomies to maintain, the accepted cost of not conflating
  "the data was bad" with "the solver was slow."
- `bess.data` stays a **leaf** (import-linter): the guard imports nothing else in
  `bess`; consumers read its result, the guard never reaches upward. Enforced by the
  existing "data is a leaf" forbidden-imports contract.
- Enforced mechanically by R1.5b's golden oracles (a hand-built feed with a known
  stuck-zero block and a known gap must be caught and correctly labeled) and a
  property test (no corrupted series ever classifies `healthy`; no false positive on
  legitimate varying negatives/zeros).

## Failure mode

A **shared** breaker firing on data corruption looks identical in the logs to a slow
solver; exactly the ambiguity that costs a debugging afternoon during an incident.
Conversely, if the R1.3/R1.5b boundary blurs, the guard might duplicate feasibility
checks (or worse, let a structural fault reach the solver assuming R1.3 owns it). The
signal that keeps them honest: R1.5b classifies *data pathology* only and defers all
feasibility judgments to R1.3, verified by tests that a trustworthy-but-infeasible
series passes the guard and is rejected by pre-flight, and vice versa.

## Alternatives considered

- **One generic breaker wrapping fetch and solve.** Rejected: a single `degraded`
  state hides whether the data or the solver failed, which is the one distinction an
  operator most needs mid-incident.
- **Fold the checks into the R1.4b loader.** Rejected: burying the outage/anomaly
  split inside `fetch_day_ahead` makes it a comment, not a testable contract; a
  separate module makes the taxonomy unambiguous in code.
- **Extend R1.3 pre-flight to cover data integrity.** Rejected: conflates "is the
  problem solvable" with "is the data trustworthy"; two different questions with two
  different fallbacks (reject-the-request vs substitute-last-known-good).
