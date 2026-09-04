# Spec R2.4b. Dual-grounded narration

**Status:** Implemented (2026-08-31). The acceptance gate ran at its specified size on
2026-09-04 and returned **no adoption**: **11 of 50 narrations were rejected, 22.0%**,
against a 5% bar fixed before the first live call. `POST /explain/narrative` does not
ship. The verifier, the deterministic fallback and the offline gates stay, and the rate
is the finding: on this task, constrained generation under a whole-response check did
not reach the quality the phase set for it.
**Release:** R2  **Depends on:** R2.4 (the `Explanation` object this narrates), R1.5 (the serving surface it extends)
**Phases:** R2.4b (approved 2026-08-31)

## Objective

Serve a short prose account of a solved dispatch in which every quantitative claim is taken from the R2.4 `Explanation`, checked against it before the response is returned, and replaced by a deterministic rendering whenever the language model is unavailable or its output fails the check.

## Motivation

R2.4 already produces the right numbers, and a per-period `reason` string beside them.
Both are machine-shaped.
A 96-period day yields 96 reason strings and no account of the day: nothing says which three periods explain its shape, or how one run's water value follows from the previous run hitting a bound.
That step is selection and ordering over an object that is already correct.
It is the one part of the task a language model is suited to, and the only part where it is not a liability.

The phase exists to answer whether that step can be taken without putting an unverifiable claim in front of a reader.
If the answer is no, the acceptance gate says so and nothing ships.

## The design driver: the model never emits a number

A language model asked to describe a schedule will produce digits, and a digit it produced is a digit nobody can trace.
Checking prose after the fact means parsing prose, which is the same problem again.

The construction avoids it.
The model is not asked for prose containing numbers.
It returns a JSON object holding an ordered list of **claims**, where each claim carries:

- a `type` drawn from a closed vocabulary, each type having a machine-checkable predicate over the `Explanation`;
- `refs`, the period or run indices the claim is about;
- `text`, a sentence in which every quantity appears as a **placeholder** such as `{price:t}` or `{mu:run}`, never as a literal.

A deterministic renderer then substitutes the placeholders from the `Explanation` and returns the result.

Three properties follow, and they are the reason for the shape:

1. A wrong number is not unlikely, it is unrepresentable. The model has no channel through which a digit can reach the reader.
2. Verification is a total function over a closed vocabulary rather than an exercise in reading prose. Each claim type is one predicate over fields that already exist.
3. The acceptance gate does not depend on model output. Seeded claim objects, including deliberately invalid ones, exercise the verifier with no network call, which is what lets this phase be gated the way every other phase is.

What the model is trusted with is which claims to make, in what order, and how to word the connective tissue between them.
What it is not trusted with is arithmetic, and it is not given the opportunity.

## Formulation reference

None. This phase adds no math.
It reports the quantities `formulation.md` § R2.4 already defines (the water value $\mu_t$, the no-trade band, the per-trade breakeven slippage) and changes none of them.

## Governing reference

None, and the absence is deliberate.
Constraining generation to a fixed schema and validating the result downstream is ordinary engineering practice, not imported theory, so citing a paper for it would be decoration.
The dual quantities the claims assert are governed by `formulation.md` § R2.4 and [the MILP dual re-solve rule](../decisions/milp-dual-resolve-rule.md), which are unchanged here.

## Design sketch

### The claim vocabulary

Six types, each with the predicate that must hold on the `Explanation` for a claim of that type to be accepted.
`P[t]` is `periods[t]`, `R[i]` is `runs[i]`, and a claim naming an index outside range is rejected before its predicate runs.

| `type` | `refs` | Predicate that must hold |
| --- | --- | --- |
| `threshold_cross` | one period `t` | `P[t].action != "idle"`, the band edge for that direction is not `None`, and the price sits on the side of it the action implies |
| `no_trade_band` | one period `t` | `P[t].action == "idle"`, `R[P[t].run].pinned`, and `band_low <= price <= band_high` |
| `tie_break_ambiguous` | one period `t` | `not R[P[t].run].pinned` |
| `flat_run` | one run `i` | `len(R[i].periods) >= 2` |
| `water_value_step` | two runs `i`, `j` | `j == i + 1`, `abs(R[i].water_value - R[j].water_value) > _PIN_TOL`, and SoC at the boundary period sits at `e_min` or `e_max` |
| `slippage_margin` | one period `t` | `P[t].breakeven_slippage_eur_mwh is not None` |

The band-edge fields are `None` on an unpinned run (R2.4), so `threshold_cross` and `no_trade_band` cannot be asserted there at all.
An unpinned run can carry only `tie_break_ambiguous`, which is the honest claim about it.

### Placeholders

| Placeholder | Resolves to |
| --- | --- |
| `{price:t}` | `P[t].price_eur_mwh`, 2 dp |
| `{mu:i}` | `R[i].water_value_eur_mwh`, 2 dp |
| `{band_low:t}` / `{band_high:t}` | `P[t].band_low_eur_mwh` / `band_high_eur_mwh`, 2 dp; rejected when `None` |
| `{slippage:t}` | `P[t].breakeven_slippage_eur_mwh`, 2 dp; rejected when `None` |
| `{soc:t}` | `schedule.soc[t]`, 3 dp |
| `{time:t}` | the period index rendered as `period N`. Not a clock label: `Explanation` carries no step length, and an index the claim already declared in `refs` is sourced either way |
| `{objective}` | `schedule.objective`, 2 dp |

### Rejection rules

The verifier rejects the whole response, not the offending claim, and falls back.
A partly-trusted narrative is worse than a dull one.

1. Any decimal digit in a `text` field outside a placeholder.
2. A `type` outside the vocabulary.
3. A `refs` index outside range, or the wrong arity for the type.
4. A predicate that does not hold.
5. A placeholder whose index is not in that claim's own `refs`, which is how a claim about period 4 would otherwise smuggle in period 9's price.
6. More claims than `max_claims`, or zero claims.
7. Malformed JSON, or a schema violation the SDK's parse step raises.
8. A placeholder that is well-formed and has nothing to resolve to, which is how a band edge reaches the renderer as `None` on an unpinned run. Added during implementation: rules 4 and 5 do not cover it, because a claim can satisfy its own predicate and still quote an absent field.

### Fallback

On any rejection, timeout, transport error, refusal, or missing credential, the endpoint returns a deterministic narrative built from the existing per-period `reason` strings at the periods where the action changes, plus the objective.
Unlike the R1.5 solver breaker, whose greedy fallback is a genuinely worse schedule, this fallback is **correct and merely dull**: the same facts, less readable.
That asymmetry is why the endpoint never returns an error for a narration failure.

## Parameters / configuration

| Parameter | Value | Where |
| --- | --- | --- |
| model | `claude-opus-5` | `NarrationConfig`, overridable |
| `output_config.effort` | `low` | request; the task is selection and phrasing, not reasoning |
| sampling controls | none | `temperature` and `top_p` are rejected with a 400 on Claude Opus 5, so output is not reproducible by construction, which is the second reason the gate cannot depend on it |
| `max_claims` | 8 | `NarrationConfig` |
| `max_tokens` | 2048 | request. Sufficient at `effort: low`; too small once thinking is on, which is how the Sonnet 5 high-effort arm failed |
| timeout | 20 s, `max_retries=0` | client; raised from the 10 s first specified, see Measured results |
| credential | `ANTHROPIC_API_KEY` | environment. Absent means the fallback path, which is how CI runs with no network |

## Interfaces

```python
class Claim(BaseModel):          # the model's output schema, via client.messages.parse
    type: Literal["threshold_cross", "no_trade_band", "tie_break_ambiguous",
                  "flat_run", "water_value_step", "slippage_margin"]
    refs: list[int]
    text: str

class Narration(BaseModel):
    claims: list[Claim]

class NarrationResult:           # what the layer returns
    text: str
    verified: bool               # False means the fallback was rendered
    rejection: str | None        # which rule fired, for logging and for the live tier

def narrate(explanation: Explanation, *, config: NarrationConfig,
            provider: Provider | None = None) -> NarrationResult: ...

def verify(narration: Narration, explanation: Explanation) -> str | None:
    """None if every claim holds; otherwise the rejection rule that fired."""

def render(narration: Narration, explanation: Explanation) -> str: ...
def fallback(explanation: Explanation) -> str: ...
```

`Provider` is a protocol with one method, so the gates inject a recorded or adversarial provider and never open a socket.

The endpoint is a new `POST /explain/narrative`, returning the `ExplainResponse` body plus `narrative`, `verified`, and `rejection`.
`POST /explain` is untouched.

## Layering (import-linter)

A new `narrate` package enters the core chain between `api` and `explain`:
`api -> narrate -> explain -> stochastic -> recourse -> optimizer -> validation -> assets`.
It may import `bess.explain` and below, and must not import `bess.api`.
This extends the existing layers contract rather than adding one, so the contract count stays at 5 KEPT. Confirmed after the module landed.

`narrate` is the only package in the chain that reaches the network, which is the reason it sits above `explain` rather than inside it: `bess.explain` stays offline, deterministic, and unchanged.

## Build tasks

- [x] `bess/narrate/claims.py`: the `Claim` / `Narration` schema and the six predicates.
- [x] `bess/narrate/verify.py`: `verify`, returning the rule that fired.
- [x] `bess/narrate/render.py`: placeholder substitution and `fallback`.
- [x] `bess/narrate/provider.py`: the `Provider` protocol, the Anthropic implementation via `client.messages.parse`, and the recorded / adversarial test providers.
- [x] `bess/narrate/narrate.py`: the pipeline, including every fallback trigger.
- [x] `api`: the `/explain/narrative` endpoint and its response model.
- [x] `pyproject.toml`: `anthropic` as an optional extra, so the core install stays offline.
- [x] the live tier, marked like the existing ENTSO-E live tests and excluded from CI: `tests/integration/test_narration_live.py`, run at its specified size on 2026-09-04.

## Golden oracles

| # | inputs | claim list | expected rendered text | why this case |
| --- | --- | --- | --- | --- |
| 1 | the R2.4 worked example: $T=3$, $\pi=[10,100,200]$, 1 MW / 2 MWh, $e_0 = e^{\mathrm{tgt}} = 0$, $\eta=1$, no wear, objective 190, one pinned run at $\mu=100$ | one `threshold_cross` at $t_0$, one `no_trade_band` at $t_1$, one `slippage_margin` at $t_2$ | exact string, pinning 10.00, 100.00 and slippage 100.00 at the discharge | substitution arithmetic, on the instance whose duals R2.4's own oracle 1 already pins |
| 2 | oracle 1, with a claim whose `text` contains the literal `100` | (rejected) | the fallback string, verbatim | rule 1, the rule the whole design rests on |
| 3 | an instance with an unpinned run, found by search: $\pi=[-55.3,-48.1,50.5,64.7]$ at $\eta=0.85$. Pinnedness needs the two idle tie-breaks to disagree, which takes a round-trip loss and a negative price together, so the $\eta=1$ worked example does not produce one | one `no_trade_band` on the unpinned run | rejected as `predicate_failed` | a band claim on an unpinned run is rejected, not softened |
| 4 | oracle 1 | one `threshold_cross` at $t_0$ whose `text` uses `{price:2}` | the fallback string | rule 5, the cross-reference smuggle |

## Property tests

- **No unsourced number.** Over Hypothesis-generated dispatch instances and accepted claim lists, every numeric token in the rendered text is either a formatted field of the `Explanation` or a period/run index the emitting claim declared in its own `refs`. This is the phase's central invariant.
- **Verifier totality.** `verify` returns either `None` or a named rule for every combination of a generated `Narration` and a generated `Explanation`, and never raises.
- **Unpinned runs.** For any instance with an unpinned run, no accepted claim list contains `threshold_cross` or `no_trade_band` on a period in that run.
- **Fallback totality.** With a provider that raises, times out, returns malformed JSON, or returns a refusal, `narrate` returns `verified=False` and a non-empty text, for every generated instance.
- **Fallback purity.** The fallback text is a function of the `Explanation` alone: two calls on equal inputs give equal output, and no provider is constructed.
- **Predicate soundness, per type.** For each of the six types, a generated claim satisfying the predicate is accepted and a generated near-miss is rejected.

## Acceptance gate

*Blocks:* nothing downstream. This phase is a leaf.
Every box must pass.

- [x] Every golden oracle reproduces its expected string exactly.
- [x] Every property test passes at the suite's standard example count.
- [x] The seeded adversarial claim set covers all seven rejection rules, and every member is rejected.
- [x] `uv run lint-imports` reports 5 contracts KEPT with `narrate` in the core chain.
- [x] The full CI suite passes with `ANTHROPIC_API_KEY` unset and no network, exercising the fallback path end to end.
- [x] **Live tier, opt-in.** Run at the specified 50 instances against the corrected prompt on 2026-09-04. Earlier readings are superseded: 50 instances against the *first* prompt (100% rejected) and 19 against the corrected one (5.3%), both recorded in Measured results because the sequence is the point.
- [x] **Adoption: not taken.** The rate at the specified size is **22.0%, 11 rejections in 50**, against a 5% bar. That is not a straddle, so the question the n=19 reading left open is closed: the endpoint does not ship.

## Measured results

All rates below are on 24-period synthetic days (`synthetic_day_ahead`, seed 11) on a
2 MWh / 1 MW asset at 0.95 round-trip with wear, narrated by `claude-opus-5` at
`effort: low` unless stated.

**The first live run rejected every narration, and the cause was the prompt.**
50 of 50 instances were rejected against a prompt that named each claim type with its
arity and domain and stated none of the conditions the verifier checks.
The model was left to infer that `water_value_step` needs adjacent runs and that
`tie_break_ambiguous` needs an unpinned one, and it inferred them wrongly.
Writing the six conditions into the prompt in the verifier's own words took the rate to
**1 rejection in 19 instances (5.3%)**.
The 100% was an instrument reading, not a result about constrained generation, and it
is recorded here because the two are easy to confuse.

**The run at the specified size rejected 22.0%, and that is the phase's answer.**
50 instances, corrected prompt, `claude-opus-5` at `effort: low`, 2026-09-04:
**11 rejections in 50**, against the 5% bar fixed before the first live call.
The n=19 reading of 5.3% sat on the bar with a 95% interval of roughly 0.1% to 26%, and
the larger sample lands near the top of that interval rather than the bottom.
The per-rule breakdown the test prints was not retained from this run, so what is
recorded here is the rate and nothing about which rules fired.
Under the spec's own reading of the bar, more than one rejected narrative in twenty
means the constrained-generation approach has not worked on this task, and that is what
is reported.

**The n=50 bar is under-powered for a 5% threshold, and it did not need to be here.**
A true 5% rate yields 0 to 6 rejections in 50, so a pass and a marginal fail at that size
are barely distinguishable, which is a real limitation of the instrument and was noted
before the run.
It does not bind on this result: 11 rejections is far outside that range, so the
under-powering would only have mattered had the answer been close.

**The oracle on the no-digit invariant was incomplete, and the live run is what found it.**
`test_a_verified_narration_contains_no_number_the_model_wrote` built its set of sourced
tokens from prices, water values, band edges, slippage and the objective, and omitted
**state of charge**, which is one of the eight placeholders and renders at three decimals
rather than two.
A correct narration was therefore rejected by the test on `2.000`, a state of charge the
solver produced and the renderer substituted.
Rule 1 (`digit_in_text`) forbids the model from writing a literal digit outside a
placeholder, so the token could not have come from the model.
The oracle now covers every placeholder the renderer can emit.
This is a defect in the gate rather than in the design, and it went unseen because no
offline fixture happened to narrate a state of charge.

**Whole-response rejection amplifies a small per-claim error rate.**
A narration carries up to 8 claims, so at a per-claim error rate of 10% the response
rejects about 57% of the time.
That is the cost of the whole-response rule (decision 3), it is a design choice rather
than a defect, and it is the reason the prompt now tells the model to prefer fewer
claims it has checked.

**A cheaper model buys latency and loses much more.** Same 8 days, same prompt:

| Model | Effort | Rejected | Median latency |
| --- | --- | --- | --- |
| `claude-opus-5` | low | 0 of 8 | 11.1 s |
| `claude-sonnet-5` | low | 2 of 8 | 6.8 s |
| `claude-sonnet-5` | high | 5 of 8 | 21.4 s |
| `claude-haiku-4-5` | none | 7 of 8 | 4.7 s |

Haiku's failures are mostly `foreign_placeholder`, and one is `digit_in_text`: it wrote
a literal number, which is the one thing the design forbids, and the verifier caught it.
The Sonnet high-effort arm is confounded and should not be read as a quality result:
every one of its failures is a schema-parse error consistent with thinking consuming the
2048 `max_tokens` and truncating the JSON.
`claude-opus-5` stays the default.

**The 10 s timeout was the binding constraint, not claim quality.**
Measured Opus 5 latency is 9.5 s to 14.8 s, median 11.1 s, so at the originally specified
budget roughly half of all *correct* narrations were discarded as timeouts.
Raised to 20 s (decision 8).

## Out of scope

- **Free-form questions about a dispatch.** Asking "what if the asset were derated tomorrow" is a tool-calling surface over `/dispatch` and `/explain`, a different phase with a different risk profile.
- **Narrating the R2.3 two-stage program.** R2.4 explains the deterministic dispatch only, so there is no stochastic `Explanation` to narrate.
- **Any influence on the dispatch decision.** `narrate` reads a solved `Explanation` and returns text. It never calls the optimizer, and the layering makes that checkable rather than promised.
- **Retrieval over the repository's documents**, and any use of the model to compute, check, or adjust a number.
- **Languages other than English**, streaming, and conversation state.
- **Prompt tuning as a measured study.** If the live rejection rate lands near the bar, that is a finding to report, not an invitation to iterate on wording until it passes.

## Decisions (reviewed 2026-08-31)

- Where does the package sit? *Proposed:* a new `narrate` package between `api` and `explain`, rather than inside `bess.explain`. That layer is pure, offline and deterministic, and a network call inside it would end all three. The cost is one more package for a small amount of code. **Resolved:** as proposed. The layering contract then states the offline property rather than leaving it to convention (2026-08-31).
- Should a rejection fail the request instead of falling back? *Proposed:* no. The R1.5 breaker returns a worse schedule on fallback, which is why `/explain` prefers a 503; here the fallback is the same facts in duller words, so returning it strictly beats an error. **Resolved:** as proposed. The asymmetry with R1.5 is the reason and it is worth stating in the endpoint docstring, so a later reader does not "fix" the inconsistency (2026-08-31).
- Reject the whole response, or drop the offending claim and render the rest? *Proposed:* reject the whole response. Dropping a claim leaves a narrative whose provenance depends on which claims survived, and the gate would then have to reason about partial output. **Resolved:** as proposed, and it is the stricter choice knowingly. Partial rendering would make the central property ("every numeric token is sourced") true of output nobody can characterise (2026-08-31).
- Which model? *Proposed:* `claude-opus-5` at `effort: low`. A cheaper model is a legitimate later change, and the live tier measures exactly the quantity that decides it, so the choice can be made on a number rather than a guess. **Resolved:** as proposed. The model id is a config field, so changing it is a config change and not a code change (2026-08-31).
- Is 5% the right adoption bar? *Proposed:* yes, and it should be set before the first live run rather than after. One rejected narrative in twenty is a visible amount of dullness; more than that and the constrained-generation approach has not worked on this task, which is worth reporting as such. **Resolved:** as proposed, and recorded here before any live call was made (2026-08-31).
- Should the fallback text say that it is the fallback? *Proposed:* yes. `verified` is in the response body, and the text itself should not be mistakable for the verified form. **Resolved:** as proposed. The fallback opens with a fixed sentence naming itself, pinned by a golden oracle (2026-08-31).
- Do the claim predicates belong in `formulation.md`? *Proposed:* no. They are consistency conditions over quantities the formulation already defines, not new math, and duplicating them there would create a second place to keep them correct. **Resolved:** as proposed. `formulation.md` is untouched by this phase (2026-08-31).
- Does writing the claim conditions into the prompt count as the tuning this spec put out of scope? **Resolved:** no. Out of scope is iterating on *wording* after seeing a near-miss. The prompt stated no conditions at all while the verifier enforced six, so the first run measured whether the model could guess unstated rules. Stating them completes the build. The distinction is recorded because it is exactly the kind of line that is easy to cross later (2026-08-31).
- The serving timeout, given measured latency. *Proposed:* raise it to 20 s and keep the endpoint. **Resolved:** raised to 20 s (decision 8). The alternative considered was moving narration off the request path entirely, since nothing about a prose account of a solved schedule is synchronous; the endpoint is kept because `/explain/narrative` already solves a MILP and re-solves an LP before narrating, so it was never a fast path (2026-08-31).
- Should a cheaper model be adopted for latency? **Resolved:** no. Measured in Measured results: the tradeoff is steep and monotone, and no cheaper arm is close to the bar (2026-08-31).
