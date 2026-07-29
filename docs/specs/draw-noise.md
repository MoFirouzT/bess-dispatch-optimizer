# Spec R2.8: Seed reproducibility of the value studies

**Status:** Draft
**Release:** R2  **Depends on:** R2.7
**Phases:** R2.8

## Objective

Measure how far each headline value median moves when only the random seed changes,
and publish that width beside the window interval already reported.

*Assumes:* the window protocol in [R2.7](study-windowing.md); the evaluation semantics
in [formulation-evaluation.md § R2.5](../formulation-evaluation.md#r25-value-evaluation-hardening-evaluation-semantics-no-optimizer-change).

## Motivation

R2.7 set out to measure window sensitivity and found something it was not looking for.
Re-running the stochastic-value study on the **same days, same asset, same knobs**, with
only the per-window seeding changed, moved the published median from +12.90 to +9.12
EUR. Neither run is more correct: both draw 30 equiprobable paths from the same
bootstrap, and the seed decides which. So about 4 EUR of a 13 EUR claim was never a
property of the market at all.

Every euro figure in [studies/](../studies/) has this width and none of them report it.
The block-bootstrap interval R2.7 added answers a different question, "how much would
this move on other delivery days", and cannot absorb seed noise: it resamples a *fixed*
set of per-window values, all of which came from one seed.

**One observation is not a measurement.** R2.7 saw the effect twice, at one seed pair,
which establishes the width is non-zero and says nothing about its size. This phase runs
enough seeds to state it.

The practical stake is the next phase. R3.1 will add a value claim on top of these, and
a claim whose reproducibility is unmeasured cannot support another one.

## Formulation reference

[`formulation-evaluation.md` § R2.5](../formulation-evaluation.md#r25-value-evaluation-hardening-evaluation-semantics-no-optimizer-change).
**No new quantity and no canonical edit.** VSS and FV are computed by the formulas
already there; this phase reports an existing quantity's reproducibility, which is a
property of the estimator rather than a new estimand.

**No optimizer delta.** `docs/formulation.md` is untouched.

## Governing reference

**None required.** Repeating a stochastic procedure under different seeds and reporting
the spread of the result is not a technique that traces to a source.

## Design sketch

For a study, a window set $W$ and seeds $s_1 \\dots s_K$, run the study $K$ times and
keep each run's **median**, giving $m_1 \\dots m_K$. Report their mean, standard
deviation and range.

Taking medians rather than pooling every window across every seed is deliberate. The
quantity whose stability matters is the one the studies pages quote; pooling would
describe a distribution nobody reports.

**This is not a confidence interval and must not be drawn as one.** A confidence
interval expresses uncertainty about an unknown parameter. This expresses something
plainer: run the published command again with a different seed and the answer moves
this far. It is the precision of the number as printed.

### What "seed" covers

The seed is measured as the **user-facing knob**, so the reported width is what someone
re-running the published command would see. For VSS it reaches only the scenario draws.
For FV it also reaches `PriceForecaster(random_state=seed)`, so the FV figure includes
model-fitting noise as well as draw noise. That is the honest scope for a reproducibility
number, and the two contributions are **not** separated here; doing so would need the
forecaster seed decoupled from the draw seed, which is an interface change this phase
does not make.

## Parameters / configuration

| Item | Value | Why |
| --- | --- | --- |
| Window set | R2.7's 260 days, NL | Holding the window fixed is what isolates the seed |
| Seeds, VSS | 0 to 9 | 2.7 min per run |
| Seeds, FV | 0 to 5 | 7.2 min per run, so fewer for a comparable budget |
| Everything else | unchanged from R2.7 | One variable |

**Tail value and bid curves are excluded.** Both report a median of exactly +0.00 in
every year at every recourse budget, so there is no headline for a seed to move. A
reproducibility width on a number pinned at zero would be noise about noise.

**Zone: NL only.** The question is about the estimator, not the market, and the
estimator does not change at the border.

## Interfaces

```python
# src/bess/studies/summary.py (additions)
@dataclass(frozen=True)
class SeedSpread:
    n_seeds: int
    mean_median: float
    sd_median: float        # population sd across seeds, not a standard error
    min_median: float
    max_median: float

    @property
    def spread(self) -> float:   # max - min

def summarize_across_seeds(medians_by_seed: Mapping[int, float]) -> SeedSpread
```

Takes the median each seed produced, so it is agnostic to which study ran and needs no
study import. Raises below two seeds.

## Build tasks

- [ ] 1. `SeedSpread` and `summarize_across_seeds`, with golden and property gates.
- [ ] 2. Live reported test in the `studies` marker tier: VSS over 10 seeds and FV over
      6, on R2.7's window set, printing each seed's median and the spread.
- [ ] 3. Run it, and record the measured widths under Measured results.
- [ ] 4. Publish the width beside the window interval on
      [stochastic-value](../studies/stochastic-value.md) and
      [forecast-value](../studies/forecast-value.md), and retire the "unquantified"
      wording in the [studies README](../studies/README.md) and
      [STATE.md](../STATE.md).

## Golden oracles

| # | inputs | expected | why this case |
|---|--------|----------|---------------|
| 1 | medians {0: 1.0, 1: 3.0, 2: 5.0} | mean 3.0, sd 1.63299…, range [1, 5], spread 4.0 | pins the arithmetic, including that `sd` is the population form |
| 2 | every seed identical | sd 0.0 and spread 0.0 | a deterministic study reports no width, rather than a small one |
| 3 | two seeds | computes rather than raising | two is the documented minimum, so the boundary is pinned |
| 4 | one seed | raises `ValueError` | a spread over one run is not a spread, and returning 0.0 would read as "reproducible" |

## Property tests

- Invariant to seed *labels*: rekeying the mapping leaves every field unchanged, since
  the seeds are names, not an ordering.
- `min_median <= mean_median <= max_median`, and `spread >= 0`, for arbitrary inputs.
- `spread == 0` exactly when every seed's median is equal.
- A non-finite median raises rather than propagating `nan` into a published width.

## Statistical gates

Live, token-gated, `studies`-marked. **Reported, never asserted.** There is no
threshold a seed spread should pass: the width is the finding, and gating it against a
bound would invite tuning the bound. The test asserts only that the runs completed and
the spread is finite.

## Acceptance gate

*Blocks:* nothing. Blocks the reproducibility sentences it adds to two studies pages.

- [ ] Golden oracles pass
- [ ] Property tests pass
- [ ] The live run completes and its widths are recorded here
- [ ] Both studies pages report the width beside the window interval
- [ ] ruff / format / mypy / lint-imports / docs-lint clean

## Out of scope

- **Separating draw noise from forecaster-fit noise in FV.** Needs the two seeds
  decoupled in the interface; see the Decisions note.
- **Reducing the noise.** Raising `n_scenarios` would shrink it and change every
  published number, which is a different phase with a different argument.
- **Tail value, bid curves, and BE**, for the reasons under Parameters.
- Any optimizer or formulation change.

## Decisions

- **Report the spread, or a standard error of the median?** *Proposed:* the spread, with
  the standard deviation beside it. A reader's question is "how much would my rerun
  differ", which max-minus-min answers directly; a standard error answers a question
  about an estimator nobody is estimating.
- **Should FV's forecaster seed be decoupled from its draw seed?** *Proposed:* no, not
  here. It would let the two noise sources be separated, which is genuinely interesting,
  but it changes a public signature to serve a diagnostic and the combined figure is the
  one a reader needs. Recorded as out of scope rather than forgotten.
- **Gate the width against a bound?** *Proposed:* no. Any bound would be picked after
  seeing the number, and a gate chosen to pass is not a gate.
