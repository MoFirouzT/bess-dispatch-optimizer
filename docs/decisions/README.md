# Decision records

Decisions that are expensive to reverse, each the stable answer to "why is it like
this?". Cheaper to write once than to keep re-deriving, and they stop a future
contributor from quietly reverting a considered choice while "improving" the code.

*Assumes: the capability map in [architecture.md](../architecture.md).*

**This directory is a curated set, not an append-only log.** Files are named by
subject, with no numbering, so a decision can be merged into a related one or
retired without leaving a gap. What lives here is what still governs the code
today. History is not this directory's job: the build record is the
[phase ledger](../specs/README.md), and the full reasoning trail for any phase is in
that phase's spec under Decisions.

The tradeoff is deliberate and worth stating. A numbered append-only series
preserves what was believed at the time, including proposals later abandoned. A
curated set instead answers "what governs this code, and why" in as few documents as
possible. This project chose the second on 2026-07-28 and consolidated twenty-six
records into seventeen at the same time.

---

## By capability

**Dispatch core**

- [Grid-side metering](grid-side-metering.md): efficiency in the SoC balance, never
  in the objective. The correctness trap the whole model rests on.
- [Per-unit SoC in config](soc-per-unit-in-config.md), absolute MWh in the model.
- [Day-ahead is 15-minute native](day-ahead-15min-native.md); the hourly core is a
  deliberate simplification.
- [Storage duration is a reported axis](storage-duration-reported-axis.md), because
  a single-duration headline can state a false general claim.

**Data feed**

- [Two circuit breakers, two taxonomies](separate-ingestion-breaker.md), with one
  shared degradation vocabulary so a solve on stale data reports as degraded.
- [No committed market data](no-committed-market-data.md): synthetic fixtures gate
  CI, real prices are fetched at runtime.

**Serving**

- [Circuit-breaker semantics for the dispatch endpoint](dispatch-circuit-breaker.md):
  availability over fidelity, and what the fallback promises.

**Price forecaster**

- [CQR over split conformal](cqr-over-split-conformal.md) as the default, because
  day-ahead prices are heteroscedastic.
- [Drift classification precedence](drift-classification-precedence.md): staleness,
  then regime, then miscalibration, each mapping to a different remedy.
- [Forecast features are aligned contemporaneously](forecast-feature-alignment.md)
  to the target, which is leakage-safe only because of publication timing.

**Scenario generation**

- [Residual-path bootstrap](residual-path-bootstrap.md), not per-hour interval
  sampling, so intra-day error correlation survives.
- [Forward selection over k-means](forward-selection-over-kmeans.md) as the primary
  reducer, with k-means kept as the compared baseline.
- [The scenario tail](scenario-tail-construction.md): a semiparametric GPD splice,
  conditioned through the scale rather than the exceedance rate.

**Stochastic dispatch**

- [Stochastic value requires risk or recourse](stochastic-value-requires-risk-or-recourse.md):
  the VSS = 0 trap, named before it could be walked into.
- [The risk-aware two-stage design](risk-aware-two-stage-design.md): structure, CVaR
  risk model, MPC recourse, and the out-of-sample estimation protocol.

**Dispatch explainability**

- [The MILP dual re-solve rule](milp-dual-resolve-rule.md): fix-and-resolve with a
  relaxed idle tie-break, and the objective-equality guard that keeps it honest.

**Cross-cutting**

- [The build substrate](modelling-solver-and-layering.md): Pyomo, HiGHS, and the
  import-linter contracts that make the layering a build gate.

---

## Writing one

Create `<short-slug>.md` from the template below when a decision is locked, and add
it to the index above under its capability.

A decision earns a file here when reversing it would be expensive: it would
invalidate a gate, force a re-derivation, or change a published number. A
conventional choice with an obvious default does not, and neither does a refactor.
If the reasoning fits in a sentence, put that sentence where the code is instead.

**Status** is `Accepted`, `Superseded`, or `Rejected`. A rejected decision is kept
only when the rejection itself is load-bearing, that is, when someone would
otherwise re-propose it.

**When a decision changes:** revise the file in place and date the change in the
front matter, or fold it into the record that supersedes it. Never leave two files
disagreeing about what governs the code.

## Template

```markdown
# <what was decided, as a statement>

**Status:** Accepted | Superseded | Rejected
**Date:** YYYY-MM-DD

## Context
The problem, the constraints, what was considered.

## Decision
The chosen approach, stated as concisely as possible.

## Consequences
What gets easier, what gets harder, and which check (CI, lint, import-linter, a
golden test) enforces this mechanically.

## Failure mode
How this could go wrong in practice, and the signal that would reveal it.

## Alternatives considered
The other options and why they were rejected.
```

**Failure mode** is the section that is not standard practice, and it is the one
worth keeping: it forces a decision to name what would falsify it.
