# Spec &lt;ID&gt;: &lt;Title&gt;

**Status:** Draft | Approved | Implemented
**Release:** R&lt;n&gt;  **Depends on:** &lt;prior phase IDs, or none&gt;

## Objective
&lt;one sentence: what this phase delivers&gt;

## Motivation
&lt;optional; include when the phase is not obviously needed, or when it closes a loop
an earlier phase left open. State the question, not the solution.&gt;

## Formulation reference
&lt;which section(s) this implements, and which file holds them (`formulation.md`,
`formulation-uncertainty.md`, `formulation-evaluation.md`), or "n/a, no new math"&gt;

## Governing reference
&lt;optional; the published source this phase's theory rests on, recorded in
`references.md`. Standard technique needs none, and saying so explicitly beats
inventing one. Never cite from memory: verify edition and section first.&gt;

## Design sketch
&lt;optional; the construction in house notation, for a phase whose shape is not
obvious from the objective&gt;

## Parameters / configuration
&lt;concrete values for this phase and where they are configured (config object, file, env)&gt;

## Interfaces
&lt;function signatures, API request/response schema, data schema; whatever applies; omit if none&gt;

## Layering (import-linter)
&lt;optional; which contracts this phase touches, and the expected KEPT count after it&gt;

## Build tasks
- [ ] &lt;task&gt;

## Golden oracles
| # | inputs | expected objective | expected schedule | why this case |
|---|--------|--------------------|-------------------|---------------|
| 1 | &lt;…&gt; | &lt;…&gt; | &lt;…&gt; | &lt;what it pins down&gt; |

## Property tests
- &lt;invariant&gt;

## Acceptance gate

*Blocks:* &lt;the phase this gate blocks&gt;. Every box must pass.

- [ ] &lt;condition&gt;

Tick a box only against evidence, and record the measured value beside it. A spec
whose **Status** is `Implemented` must have no unticked box; `scripts/lint_docs.py`
enforces that, because "we meant to tick it" and "it passed" are indistinguishable
six weeks later.

## Measured results
&lt;optional; what the phase actually found, when the finding is the deliverable.
Reader-facing write-ups belong in `docs/studies/`; this is the builder's record.&gt;

## Out of scope
- &lt;item&gt;

## Decisions

Phase-local formulation / interface / build decisions only. Roadmap and
positioning questions stay in the Tier 0 planning log, never here.

Pose each with a proposed answer, then resolve it in place at review, keeping the
proposal so the section becomes the decision trail rather than a list of questions
answered elsewhere. This is where a later reader is sent for *why*, so it is the one
section that must not be trimmed on the way to green.

Promote a decision to a record in `docs/decisions/` only when it is cross-cutting and
expensive to reverse, and leave a pointer here.

- &lt;question&gt; *Proposed:* &lt;recommendation&gt;.
- &lt;question&gt; **Resolved:** &lt;decision + rationale&gt; (YYYY-MM-DD).
