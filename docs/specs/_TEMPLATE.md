# Spec &lt;ID&gt;: &lt;Title&gt;

**Status:** Draft | Approved | Implemented
**Release:** R&lt;n&gt;  **Depends on:** &lt;prior phase IDs, or none&gt;

## Objective
&lt;one sentence: what this phase delivers&gt;

## Formulation reference
&lt;which section(s) of `docs/formulation.md` this implements, or "n/a, no new math"&gt;

## Parameters / configuration
&lt;concrete values for this phase and where they are configured (config object, file, env)&gt;

## Interfaces
&lt;function signatures, API request/response schema, data schema; whatever applies; omit if none&gt;

## Build tasks
- [ ] &lt;task&gt;

## Golden oracles (exact expected values)
| # | inputs | expected objective | expected schedule | why this case |
|---|--------|--------------------|-------------------|---------------|
| 1 | &lt;…&gt; | &lt;…&gt; | &lt;…&gt; | &lt;what it pins down&gt; |

## Property tests (invariants that hold for any valid input)
- &lt;invariant&gt;

## Acceptance gate (all must pass before the next phase)
- [ ] &lt;condition&gt;

## Out of scope (explicit; do not build here)
- &lt;item&gt;

## Open questions

Phase-local formulation / interface / build decisions only. Roadmap and
positioning questions stay in the Tier 0 planning log, never here.

Pose each with a proposed answer, then resolve it in place at review, keeping
the resolved line so the section becomes the decision trail. Promote a decision
to an ADR only when it is cross-cutting, and leave a pointer here.

- &lt;question&gt; *Proposed:* &lt;recommendation&gt;.
- &lt;question&gt; **Resolved:** &lt;decision + rationale&gt; (YYYY-MM-DD).
