# ADR-0005: Commit real fixture data so the suite runs without an API token

**Status:** Rejected
**Supersedes / Superseded by:** superseded before implementation by the
no-committed-data policy in the [R1.4b spec](../specs/R1.4b-entsoe-loader.md) open
questions (resolved 2026-06-26) and the conventions licensing rule.
**Date:** 2026-06-26 *(estimated; rejected at the R1.4b review)*

*Back-filled (0001–0008); the date is when the proposal was rejected, not when
this file was written. Recorded as **Rejected** so the original proposal is not
mistaken for current policy.*

## Context

An early proposal was to commit a real ENTSO-E day-ahead price slice as a test
fixture, so the suite would run offline and token-free with realistic prices.
This conflicts with ENTSO-E's data licensing: real / third-party price data may
not be redistributed in the repository.

## Decision

**Rejected.** Do not commit any real or third-party price data. Instead:

- **synthetic fixtures** drive CI and the golden/property gates (deterministic,
  redistributable, token-free);
- **ENTSO-E data is fetched live at runtime only**, cached under the gitignored
  `data/cache/`, and never committed;
- the live integration test is gated on `ENTSOE_API_TOKEN` + network and **never
  runs in CI** (see the `integration` marker in `pyproject.toml`).

## Consequences

- **Easier:** CI is licence-clean and token-free; no redistribution exposure.
- **Harder:** realistic-data checks (the sanity-band / integration test) require a
  token and network, so they run locally, not in CI.
- **Enforced by:** the `integration` pytest marker (skips without token/network),
  `data/cache/` in `.gitignore`, and the R1.4b parser test using a *synthetic* A44
  XML rather than a captured real document.

## Failure mode

A contributor commits a captured real slice "just for tests." Signal: a data file
with real prices appears in a diff. Mitigation: the policy is stated in the R1.4b
spec, the conventions licensing note, and this ADR; review rejects committed price
data.

## Alternatives considered

- **Commit a small real slice (the original proposal).** Rejected: violates
  ENTSO-E licensing; synthetic fixtures give deterministic, redistributable gates
  and live fetch covers realistic-data validation without redistribution.
