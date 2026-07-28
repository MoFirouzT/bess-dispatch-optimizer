# No real or third-party market data is committed

**Status:** Accepted
**Date:** 2026-06-26 *(decided at the loader review)*

*This record was originally filed as a rejected proposal ("commit a real price
slice as a fixture"). It was restated on 2026-07-28 as the policy that came out of
that rejection, which is what the rest of the project actually cites.*

## Context

An early proposal was to commit a real ENTSO-E day-ahead price slice as a test
fixture, so the suite would run offline and token-free against realistic prices.
That conflicts with ENTSO-E's data licensing: real and third-party price data may
not be redistributed in the repository.

The project still needs deterministic gates that run in CI, and it still needs
validation against realistic data. Those two needs have to be met separately.

## Decision

**No real or third-party price data is committed, ever.** Instead:

- **Synthetic fixtures** drive CI and the golden and property gates: deterministic,
  redistributable, token-free.
- **ENTSO-E data is fetched live at runtime only**, cached under the gitignored
  `data/cache/`, and never committed.
- **Live integration tests are gated** on `ENTSOE_API_TOKEN` plus network and
  **never run in CI**.

## Consequences

- **Easier:** CI is licence-clean and token-free, with no redistribution exposure,
  and any reader can run the suite.
- **Harder:** realistic-data checks require a token and network, so they run
  locally rather than in CI. Every headline number in the README is therefore
  reproducible only with a token, which the README states.
- **Enforced by:** the `integration` pytest marker that skips without a token,
  `data/cache/` in `.gitignore`, and the loader's parser test using a *synthetic*
  A44 XML document rather than a captured real one.

## Failure mode

A contributor commits a captured real slice "just for tests". Signal: a data file
with real prices appears in a diff. Mitigation: the policy is stated here, in the
loader spec, and in the conventions licensing note; review rejects committed price
data.

## Alternatives considered

- **Commit a small real slice.** The original proposal. Rejected: it violates
  ENTSO-E licensing, and synthetic fixtures plus live fetch cover both needs
  without redistribution.
- **Check in a recorded HTTP fixture of a real response.** Same licensing problem
  wearing a different file extension.
