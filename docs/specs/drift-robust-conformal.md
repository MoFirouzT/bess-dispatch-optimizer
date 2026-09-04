# Spec R2.1g: Drift-robust conformal intervals

**Status:** Implemented (2026-08-31), **gate re-opened and the null inverted by amendment
(2026-09-03)**. The 2026-08-31 gate returned **no adoption** on a run whose worst year
was 2022, at most +0.019 against a +0.03 bar. On the extended span at the corrected monthly
cadence the worst year is 2021 and the composed arm adds **+0.146 NL and +0.150 BE**, clearing
every threshold in both zones. **Nothing in `src/bess/forecaster/forecast.py` has changed**:
adoption waits on the refit cadence, which the evaluation harness sets and the serving path
does not implement. The phase's other finding stands: refitting monthly rather than annually
is worth +0.18 on 2022 and +0.34 on 2021.
**Release:** R2  **Depends on:** R2.1 (the forecaster and its conformal wrappers), R2.1b (the drift monitor this phase answers), R2.1d (the fold layout and gate statistics), R2.1e (the target settings held fixed), R2.1f (the selection discipline and the coverage-versus-trend measurement)
**Phases:** R2.1g

## Objective

Replace the conformal calibration step with two constructions that survive a price
regime shift, a weighted quantile over the calibration scores and an online update of
the target level, then measure what each buys and what it costs in width.

*Assumes:* the conformal construction in
[formulation-uncertainty.md § R2.1](../formulation-uncertainty.md#r21-probabilistic-price-forecast-conformal-intervals-no-optimizer-change);
the fold layout and gate statistics in [R2.1d](forecaster-evaluation.md);
the selection discipline in [R2.1f](interval-sharpness.md);
the seed-width rule in [R2.8](draw-noise.md).

## Motivation

R2.1 shipped a coverage guarantee that holds **for exchangeable data**, and day-ahead
prices are not exchangeable.
Every phase since has managed that assumption without removing it: R2.1b detects its
breakdown, R2.1e de-levels the target, R2.1d rebuilt the harness to measure coverage
across regimes.

R2.1f then measured the cost, which until now had only been asserted.
At one fixed placement on NL, pooled coverage runs **0.897 in 2024, 0.887 in 2023,
0.847 in 2022 and 0.791 across the 2021 crisis ramp**, against monthly means climbing
77 to 238 EUR/MWh.
Coverage falls monotonically with how hard the level trends.
That is not noise around a nominal 0.9 and not a modelling defect: it is the
guarantee's precondition failing, in the conditions a storage operator most needs an
interval.

The response the project ships today is a 28-day rolling recalibration, and it is
measured: carried across a season boundary it lifts coverage from 0.788 to 0.820 at
roughly 38 percent more width ([R2.1e](target-normalization.md), finding 6).
An improvement, still outside the band, and it comes with **no statement of how much
coverage the drift costs**.
Recalibration is a heuristic wearing the clothes of a guarantee.

Two published constructions replace the heuristic, and they fix different halves of the
problem:

- **Weighted conformal** fixes the *calibration set*.
  Old scores get less weight, and the resulting coverage shortfall is **bounded by a
  computable quantity** rather than left unstated.
  It cannot do better than the recent window contains.
- **Adaptive conformal inference (ACI)** fixes the *target level*.
  It watches realized misses and moves the nominal level to compensate, with a
  long-run coverage guarantee that holds under **arbitrary** distribution shift.
  It buys that coverage with width, and its guarantee attaches to a long sequential
  run rather than to any one block.

They compose, because both are modifications of a single scalar, the conformal margin
$\hat s$.
This phase builds both, measures each alone and together, and reports whichever of
the four combinations the gate accepts, including "none of them".

**A null is a result.**
If the width cost exceeds the thresholds below, the phase reports that and the shipped
calibration does not change, as R2.1f did.

## Formulation reference

[`formulation-uncertainty.md` § R2.1](../formulation-uncertainty.md#r21-probabilistic-price-forecast-conformal-intervals-no-optimizer-change).

**No optimizer delta.** No constraint, variable, objective term, or efficiency
placement changes; `docs/formulation.md` is untouched.

**Two canonical edits, in the same change** (CLAUDE.md §1).

1. §R2.1 gains the weighted-quantile construction and its coverage-gap bound, and the
   ACI recursion and its long-run bound, as the two paragraphs sketched below.
   Both are new theory and neither is derivable from what is written there now.
2. §R2.1's "Considered but out of scope" line currently reads "adaptive conformal for
   distribution shift (ACI); noted for R2.1b, not built here".
   That line is what this phase reverses, so it moves into scope and the out-of-scope
   list keeps only what still stays out (conditional coverage, cross-conformal and
   jackknife+, the nonexchangeable full-conformal and jackknife+ variants).

## Governing reference

Both verified from source on 2026-08-31, not cited from memory.
Recorded in [`references.md`](../references.md) under R2.1g in the same change.

- **R. F. Barber, E. J. Candès, A. Ramdas, R. J. Tibshirani, "Conformal prediction
  beyond exchangeability", *The Annals of Statistics* 51(2):816-845, April 2023**
  (DOI 10.1214/23-AOS2276; preprint arXiv:2202.13415).
  *Governing* for the weighted construction.
  Drawn on: the normalized weights (eq. 12), the nonexchangeable split-conformal
  interval (eq. 13), **Theorem 2a** (the coverage lower bound), and the two worked
  corollaries in §5.4 (bounded drift and changepoint).
  Verified: Theorem 2a is stated for a **pre-fitted** model independent of the
  calibration data, which is the condition this project's temporal split already
  satisfies and which the gate below pins.
- **I. Gibbs & E. J. Candès, "Adaptive Conformal Inference Under Distribution Shift",
  *Advances in Neural Information Processing Systems 34*, 2021.**
  *Governing* for the online construction.
  Drawn on: the miscoverage indicator and the update (eq. 2), **Lemma 4.1** (the
  iterate stays in $[-\gamma, 1+\gamma]$), and **Proposition 4.1** (the long-run
  coverage bound).
  Verified: Proposition 4.1 is a deterministic, almost-sure statement with **no
  assumption on the data-generating distribution**, which is why it can be gated as a
  property test rather than a statistic.

*Notation reconciled to house style.*
Both papers write the miscoverage level as $\alpha$, which matches the house use in
§R2.1 and does not collide with the CVaR tail level in §R2.3 (a different file's
section, and the two never appear in one expression).
The conformal margin stays the house $\hat s$, not the papers' $\hat q$.
The decay parameter is written $\rho$ and the ACI step size $\gamma$; neither symbol is
in use elsewhere in the formulation.

## Design sketch

### Weighted conformal (the calibration set)

Let the calibration block hold $n$ scores $E_1, \dots, E_n$ in time order, $E_n$ the
most recent, with $E_i$ the R2.1 CQR score
$\max\{\hat q_{\alpha/2}(x_i) - y_i,\ y_i - \hat q_{1-\alpha/2}(x_i)\}$
(or $|y_i - \hat\mu(x_i)|$ for the split method).
Attach weights $w_i = \rho^{n+1-i}$ with $\rho \in (0, 1]$, normalize as

$$ \tilde w_i = \frac{w_i}{w_1 + \dots + w_n + 1}, \qquad \tilde w_{n+1} = \frac{1}{w_1 + \dots + w_n + 1}, $$

and take the margin as the weighted quantile of the score distribution **including an
atom at $+\infty$**:

$$ \boxed{ \hat s = Q_{1-\alpha}\Big( \sum_{i=1}^{n} \tilde w_i \delta_{E_i} + \tilde w_{n+1} \delta_{+\infty} \Big). } $$

The $+\infty$ atom is not decoration.
It is what makes the bound finite-sample, and it is what makes the interval refuse to
answer when the weights have thrown away too much of the calibration set: if
$\tilde w_{n+1} > \alpha$ the quantile is $+\infty$ and the interval is the whole line.
The code must return that rather than silently falling back to the largest score.

**Coverage bound (Theorem 2a).** Writing $Z$ for the calibration-plus-test sequence
and $Z^i$ for the same sequence with points $i$ and $n+1$ swapped,

$$ \boxed{ \mathbb P\big(y_{n+1} \in \hat C_n(x_{n+1})\big) \ \ge\ 1 - \alpha - \sum_{i=1}^{n} \tilde w_i \cdot d_{\mathrm{TV}}\big(R(Z), R(Z^i)\big). } $$

The subtracted term is the **coverage gap**, and it is the quantity nothing in the
project currently states.
Two corollaries make it reportable.
Under a changepoint $k$ steps in the past, the gap is at most $\rho^{k}$.
Under drift bounded by $d_{\mathrm{TV}}(Z_i, Z_{n+1}) \le \epsilon(n+1-i)$, it is at
most $2\epsilon/(1-\rho)$.
Both are computable from $\rho$ alone once $k$ or $\epsilon$ is named, so the phase can
publish "at this $\rho$, a regime break one week ago costs at most X coverage" instead
of the current silence.

At $\rho = 1$ every $\tilde w_i = 1/(n+1)$ and $\hat s$ is the
$\lceil (1-\alpha)(n+1) \rceil$-th smallest score, which is R2.1's construction exactly.
The incumbent is therefore a point in this family, not a thing to be compared against
it, and the identity is golden oracle 1.

### Adaptive conformal inference (the target level)

Run the forecaster forward through delivery days.
On day $t$ the interval is emitted at level $\alpha_t$ rather than the fixed $\alpha$;
after the day settles, its realized miscoverage $\mathrm{err}_t \in [0, 1]$ is known,
and

$$ \boxed{ \alpha_{t+1} = \alpha_t + \gamma(\alpha - \mathrm{err}_t), \qquad \gamma > 0. } $$

Under-covering pushes $\alpha_t$ down, which widens the next interval; over-covering
pulls it back up.
By Lemma 4.1 the iterate stays in $[-\gamma, 1+\gamma]$, and by Proposition 4.1, for
every $T$ and **with no assumption on the data**,

$$ \boxed{ \Big| \frac{1}{T}\sum_{t=1}^{T} \mathrm{err}_t - \alpha \Big| \ \le\ \frac{\max\{\alpha_1,\ 1 - \alpha_1\} + \gamma}{\gamma T}. } $$

This is the shape of guarantee the project does not currently have anywhere: it holds
through the 2021 ramp, through a changepoint, through anything.
What it does **not** give is coverage on any particular block, which is exactly why the
existing 5-day-block gate cannot score it and why this phase builds a sequential
harness.

**The published update is per prediction; ours is per day.**
Twenty-four hourly outcomes settle at once, so the step is one update per delivery day
using that day's miss *rate*, $\mathrm{err}_t \in [0, 1]$ rather than $\{0, 1\}$.
Both proofs carry: they use only that a 24-hit day gives a rate of 0 and a 24-miss day
a rate of 1. That is **our** extension rather than something the paper states, so it is
gated on adversarial sequences rather than asserted.

**The clamp, and what it costs.**
$\alpha_t < 0$ means an interval of infinite width, and the R2.2 scenario layer cannot
consume that.
The emitted level is therefore clamped to $[\alpha_{\min}, \alpha_{\max}]$ while the
recursion carries the unclamped $\alpha_t$.

**Clamping does not pause Proposition 4.1, it removes the feedback the proposition
rests on.**
Lemma 4.1 holds because a level below 0 makes the interval the whole line, so the day
cannot miss, and a level above 1 makes it empty, so the day cannot hit.
With the emitted level pinned inside the clamp, neither saturation happens: a level
above 1 still produces an ordinary interval that can cover, nothing forces a miss, and
the iterate can travel arbitrarily far.
The a-priori bound then stops applying, and it does not come back when the clamp stops
binding.

What survives is the **exact identity** underneath the proposition.
Expanding the recursion telescopes, for any sequence at all, to

$$ \boxed{ \Big| \frac{1}{T}\sum_{t=1}^{T} \mathrm{err}_t - \alpha \Big| = \frac{|\alpha_{T+1} - \alpha_1|}{\gamma T}. } $$

Proposition 4.1 is this identity plus Lemma 4.1's bound on $|\alpha_{T+1} - \alpha_1|$.
The identity holds through any clamping, so it is what the sequential gate reports: a
run whose iterate wandered far reports a correspondingly large gap, in place of a bound
that quietly stopped being true.
The count of clamped steps is reported beside every coverage number, and a gate below
requires it to be rare.
An adaptive method that silently saturates is a fixed-alpha method with extra
machinery.

*This replaces the approved wording, which said the guarantee was void only while the
clamp bound. The property test rejected that reading before any real data was touched,
which is what writing the gates first is for.*

### Composition

Both constructions modify $\hat s$ and nothing else, so they stack: the margin is the
weighted quantile of the calibration scores taken at level $1 - \alpha_t$.
The phase measures four arms (neither, weights only, ACI only, both) so the
contribution of each is separable rather than inferred from a bundle.
R2.1e is the precedent: measuring three changes together read as a null and the
separated measurement did not.

## Parameters / configuration

| Knob | Values searched | Default (incumbent) |
| --- | --- | --- |
| `weight_half_life_days` | `None`, 14, 7, 5, 3, 2 | `None` (that is $\rho = 1$, R2.1 exactly) |
| `aci_gamma` | 0.0, 0.0025, 0.005, 0.01, 0.02 | 0.0 (no adaptation) |
| `aci_alpha_clamp` | fixed | `(0.01, 0.5)` |
| `aci_step` | fixed | one update per delivery day |
| `refit_every_days` | fixed | **30 (monthly)** since the 2026-09-03 amendment below; 365 until then, and kept as a reported contrast |

`weight_half_life_days` is configured in days and converted to a per-point
$\rho = 2^{-1/(24 h)}$ for hourly data, because a half-life in days is the quantity a
reader can reason about and $\rho = 0.9985$ is not.
`None` maps to $\rho = 1$ and must reproduce R2.1 bitwise.

**Both grids were moved down after the synthetic probe below**, which is what a probe
is for. The approved values started at a 60-day half-life and ran $\gamma$ up to 0.05.
A 60-day half-life is inert against a calibration block of roughly 110 days, and
$\gamma = 0.05$ saturates the clamp on a third of days, so half of each approved grid
was dead on arrival. The action is at 2 to 7 days and at $\gamma \le 0.01$.

Everything else stays at its shipped R2.1e/R2.1f value: features, lags,
`season_encoding`, `rolling_stats`, `normalize_target`, `confidence_level=0.9`,
`method="cqr"`, and the LightGBM defaults R2.1f searched and left unchanged.

## Interfaces

A new `conformal.py` under `bess.forecaster`, pure numpy, importing nothing from the
package (so the drift and evaluation gates run without the `forecast` group):

```python
def decay_weights(n: int, *, half_life_days: float | None, dt_h: float = 1.0) -> np.ndarray:
    """w_i = rho ** (n + 1 - i), most recent last. `None` gives all-ones (rho = 1)."""

def weighted_quantile(scores: np.ndarray, weights: np.ndarray, *, level: float) -> float:
    """Barber et al. eq. 13, including the +inf atom. Returns inf when it binds.

    Raises if any weight is outside [0, 1]: the theorem is stated for w_i in [0, 1],
    and rescaling them changes the +inf atom's mass rather than cancelling out.
    """

def cqr_score(y, lower, upper) -> np.ndarray: ...
def split_score(y, point) -> np.ndarray: ...

def changepoint_gap_bound(*, half_life_days: float | None, lag_days: float) -> float:
    """Theorem 2a under a changepoint `lag_days` ago: rho ** k. 1.0 when rho = 1."""

def drift_gap_bound(*, half_life_days: float | None, epsilon: float) -> float:
    """Theorem 2a under Lipschitz drift: 2 * epsilon / (1 - rho). inf when rho = 1."""

@dataclass(frozen=True)
class AciState:
    alpha: float           # the unclamped iterate
    alpha_emitted: float   # after the clamp; the level the interval was built at
    alpha_target: float
    gamma: float
    clamp: tuple[float, float]
    n_updates: int
    n_clamped: int

def aci_update(state: AciState, *, err: float) -> AciState: ...
def aci_bound(*, alpha_1: float, gamma: float, n_updates: int) -> float:
    """Proposition 4.1's right-hand side. Valid only on an unclamped run."""

def aci_realized_gap(*, alpha_1, alpha_final, gamma, n_updates) -> float:
    """The exact |mean(err) - alpha|, read off the iterate. Holds through clamping."""
```

`PriceForecaster` gains `weight_half_life_days: float | None = None`.
When it is `None` the conformal step stays MAPIE's and the output is byte-identical to
R2.1e; when it is set, the margin is computed by the functions above from scores the
forecaster already has.

The sequential harness lands in `evaluate.py` beside the block harness:

```python
@dataclass(frozen=True)
class SequentialCoverage:
    """Pooled and per-year coverage, both widths, the alpha path, the clamp count,
    the Prop 4.1 bound, the exact telescoping gap, and the Thm 2a gap bound."""

def sequential_coverage(
    prices: pd.Series,
    *,
    start: pd.Timestamp,
    train_days: int = 365,
    refit_every_days: int = 365,
    weight_half_life_days: float | None = None,
    aci_gamma: float = 0.0,
    ...
) -> SequentialCoverage: ...
```

## Layering (import-linter)

The new module imports numpy and pandas only; `forecast.py` and `evaluate.py` import
it.
Intra-package, no contract touched; the expected KEPT count stays **5**.

## Build tasks

- [x] `conformal.py`: weights, weighted quantile with the `+inf` atom, both scores, the two gap bounds, the ACI state and update, `aci_bound`, `aci_realized_gap`
- [x] Re-derive Lemma 4.1 and Proposition 4.1 for the day-batched `err` in $[0, 1]$: both carry, since a 24-hit day gives a rate of 0 and a 24-miss day a rate of 1, which is all the saturation argument uses. The re-derivation also found that the **clamp** breaks the lemma's feedback, recorded under Decisions
- [x] Thread `weight_half_life_days` through `PriceForecaster.fit`, `predict_interval`, and `recalibrate`; `None` stays MAPIE and stays byte-identical. `predict_interval` also gained an `alpha` override, which is how the ACI arm moves the level without a refit
- [x] `sequential_coverage` in `evaluate.py`, carrying the ACI iterate across days and refitting on the schedule; leakage, the inert baseline, per-year partitioning and state carry-over are gated
- [x] Golden + property tests below, written failing first; the ACI pair rejected the approved clamp wording before any data was touched
- [x] Synthetic drift generators, seeded and committed: `synthetic_drift` in `bess.data` with calm, ramp, changepoint and volatility regimes, gated in `tests/property/test_drift_regimes.py`. A fourth regime was added beyond the three specified: volatility drift moves the scores without moving the level, which is the only case that separates what the two arms repair
- [x] Live gate module for the arms on NL and BE, marked `studies`: `tests/integration/test_drift_robust_live.py`. **Five arms, not four**: the symmetric-unweighted baseline was added because turning on weighting also switches the CQR correction, so comparing against the shipped model would measure two changes at once. Written and collecting; **first run 2026-09-03**, which failed four boxes at the approved annual cadence and produced the amendment below
- [!] Decide the data span and refresh the cache: **decided (extend to 2019-01-01) and encoded as `EXTENDED_SPAN` beside an untouched `SPAN`. The fetch landed 2026-09-03** once the outage ended, and both zones cache 2019 to 2025. The original-span reproduction check is still owed
- [x] Report the arms with both widths per R2.8 and the gap bound beside each coverage number: [studies/drift-robust-conformal](../studies/drift-robust-conformal.md). The day-block interval is reported per arm; the **seed spread is structurally zero** and is not reported as a stability result, per the carried R2.1f finding that deterministic single-threaded LightGBM gives `random_state` no entry point into the fit
- [!] Adoption: **not reached.** No arm cleared the worst-year coverage bar, so no default changed and the R2.1/R2.1d/R2.1f gates were not re-run
- [x] `formulation-uncertainty.md` §R2.1 edits (the two constructions; the out-of-scope line)
- [!] `references.md` R2.1g entry written; the **ledger row is deliberately not written**, since a row records what a phase found and this one has not measured yet

## Golden oracles

The math here is exact arithmetic on top of an exact recursion, so this phase has real
oracles despite being a calibration change.

| # | inputs | expected | why this case |
| --- | --- | --- | --- |
| 1 | `weight_half_life_days=None` on a fixed seed and price window | point, lower, upper bitwise identical to the shipped R2.1e model | the opt-in identity, and proof, which cannot be faked, that the weighted path contains the incumbent rather than approximating it |
| 2 | 4 scores `[1, 2, 3, 10]` with hand-written weights, level 0.9 | the hand-computed $\hat s$, with the atom the level lands on named | pins the weighted-quantile arithmetic, including which side of an atom the level falls |
| 3 | weights small enough that $\tilde w_{n+1} > \alpha$ | $\hat s = \infty$, and the interval is the whole line | the degenerate case, which a naive implementation returns as `max(scores)` and silently voids the bound |
| 4 | a weight vector containing 1.5 | `ValueError` | the theorem is stated for $w_i \in [0, 1]$; rescaling is not a no-op because it moves the $+\infty$ atom's mass |
| 5 | $\alpha_1 = 0.1$, $\gamma = 0.01$, the miss sequence `[1,0,0,1,0,0,0,0,1,0]` | the 10-step $\alpha$ path, to floating-point exactness | pins the recursion, which is the whole of ACI |
| 6 | $\alpha_1 = 0.1$, $\gamma = 0.01$, $T = 100$ | `aci_bound` = 0.91 exactly, that is $(0.9 + 0.01)/(0.01 \times 100)$ | pins the bound the run is scored against, including the $\gamma T$ denominator |
| 7 | `half_life_days=7`, `lag_days=7` | `changepoint_gap_bound` = 0.5 exactly | pins the corollary a reported gap number rests on |
| 8 | `half_life_days=None`, any lag | gap bound 1.0, and the Lipschitz bound infinite | the incumbent's honest bound: unweighted conformal promises nothing off-exchangeability, and the code says so rather than returning 0 |

## Property tests

- **The telescoping identity holds for every sequence**, clamped or not: $|\overline{\mathrm{err}} - \alpha| = |\alpha_{T+1} - \alpha_1| / (\gamma T)$. The strongest of the three, since it assumes nothing at all.
- **Proposition 4.1 holds on realizable unclamped sequences.** The miss rate is adversarial wherever the level is in $[0, 1]$; it is forced only where the interval itself forces it (whole line cannot miss, empty cannot hit). A sequence ignoring that is not a run, it is an inconsistency.
- **Lemma 4.1 holds** on the same realizable sequences: the unclamped iterate stays in $[-\gamma, 1+\gamma]$.
- **Clamping can unbind the iterate**, demonstrated rather than described: sixty covered days at a clamped level walk it past $1+\gamma$, which the unclamped recursion cannot do. Gated so the limitation cannot be quietly lost.
- $\gamma = 0$ reproduces the fixed-level path exactly, and `n_clamped` is 0.
- **The clamp is accounted:** `n_clamped` counts exactly the steps where `alpha_emitted` differs from `alpha`.
- `weight_half_life_days=None` gives an interval bitwise equal to R2.1's, for every generated input, not only the golden seed.
- $\hat s$ is non-increasing in $\alpha$ and non-decreasing in every score.
- Shortening the half-life moves weight toward recent scores: with scores increasing in time, $\hat s$ is non-decreasing as the half-life shortens.
- `changepoint_gap_bound` is decreasing in `lag_days`, increasing in the half-life, and lands in $[0, 1]$.
- **The pre-fit condition holds:** for every fold and every sequential refit, the calibration index range is disjoint from and strictly later than the training range. Theorem 2a needs the model independent of the calibration data, and nothing currently asserts it.

## Acceptance gate

*Blocks:* adoption of a new default calibration, and any later phase that consumes
interval width. Every box must pass.

**Superseded configuration (2026-09-03).** Every box below was scored on `SPAN` at a monthly refit, before the `EXTENDED_SPAN` reporting run the amendment sets. The adoption boxes are re-scored underneath the amendment; the rest are owed a re-run.

- [x] All arms ran to completion on NL and BE and reproduce bitwise on a second run: coverage, width, per-year split and the final level all identical (NL, composed arm, 0.9016233667346877)
- [!] Worst-year coverage up at least 0.03: **failed.** Best gain is **+0.019** on NL (0.870 to 0.889, composed arm) and **nothing** on BE (0.890 to 0.886). This is the box the null turns on
- [x] Best-calibrated year stays in band: every arm lands 0.904 to 0.917 on its best year in both zones, so nothing traded a shift failure for a calm-regime one
- [x] Median width rises by less than 10%: every arm lands within **2%** of the baseline (-1.9% to +1.6%). It passes trivially, and for the wrong reason: at a monthly refit there is no coverage left to buy, so no arm is spending width
- [!] `max_hour_deviation` no worse: **NL passes** (0.055 against 0.056), **BE misses by 0.001** (0.042 against 0.041). Recorded as a miss rather than waved through as noise, because the constraint is stated as no-worse and R2.1f rejected a candidate on this same metric
- [!] Pinball skill: **not run.** It is an adoption-conditional check and adoption was not reached; running it would not change the verdict
- [x] The identity holds on real data (realized 0.001692233 against 0.001692233 expected) and the run was **clamp-free**, so Proposition 4.1's published bound applies rather than only the identity: 0.00169 against a bound of 0.132
- [x] Clamp binding **0.0%** of 1369 days at a monthly refit. The 19.4% seen at an annual refit was an artefact of the stale baseline, not a property of the step size
- [x] Gap bound published beside every coverage number: 0.500 at a 7-day half-life and a 7-day changepoint lag, against 1.000 (no claim at all) unweighted
- [x] Recorded as the null it is, arms reported separately, with the refit-cadence confound that nearly hid it stated first

## Measured results

*Written during implementation; superseded in part by the 2026-09-03 amendment below.*

**A pre-existing defect was found en route: the shipped CQR interval is not the one
§R2.1 describes.**
Oracle 1b compares our weighted margin at $\rho = 1$ against MAPIE's, and they did not
match.
The cause is not in the new code.
§R2.1 defines CQR with **one** signed score and **one** margin $\hat s$ on both bounds,
which is also the form Theorem 2a is stated for.
MAPIE's `predict_interval` defaults to `symmetric_correction=False`, a **separate
constant per side**, and that is what has shipped since R2.1.
Against `symmetric_correction=True` our implementation agrees to **0.0** on both bounds
and both methods, so the divergence is entirely shipped-default versus documented
construction, and it is CQR-only.

**No coverage number is wrong**: both are valid constructions with the same marginal
guarantee, which is why four phases of coverage gates passed either way.
What is wrong is that the single source of truth does not describe what executes.
The asymmetric variant is the **narrower** of the two here, so the shipped model is not
merely over-covering.

Two consequences.
The divergence is pinned by
`test_the_shipped_default_is_the_asymmetric_variant_not_the_documented_one`, which fails
on the day code and doc are brought into line.
And it is a **confound this phase must not walk into**: turning on weighting also
switches to symmetric, so comparing against the shipped model would measure two changes
at once, the reading error R2.1e had to undo.
Every arm therefore runs symmetric, and the incumbent-equivalent baseline is
**symmetric, unweighted**, not the shipped model.

**A first reading on synthetic drift, which is not the gate**, is in
[studies/drift-robust-conformal](../studies/drift-robust-conformal.md): the harness runs end
to end and the arms separate in the direction the theory predicts.

### Synthetic probe and knob selection

Moved to [studies/drift-robust-conformal](../studies/drift-robust-conformal.md), which is
where the reader-facing write-up belongs and where this spec's line budget sends it. What it
decided for the build: **half-life `None` and $\gamma = 0.005$**, the only arm feasible on all
four regimes, with ACI the arm that moves coverage and the clamp gate, not coverage, picking
$\gamma$. Both approved grids were moved down after the probe and the approved values are
recorded there as having been wrong. The weighted arm stays in the run anyway, because it is
the only one that yields a stated bound.

## Amendment: the reporting run's refit cadence (2026-09-03)

**The committed gate and the recorded gate results are two different experiments, and the
difference between them is the confound this phase named.** `test_drift_robust_live.py` ran for
the first time on 2026-09-03 and failed four boxes. It runs `refit_every_days=365` on
`EXTENDED_SPAN` (2100 scored days), as the Parameters table specifies; every recorded gate
number was measured at a monthly refit on `SPAN` (1369 days). The numbers are in
[studies/drift-robust-conformal](../studies/drift-robust-conformal.md); the tell is 2022 at
0.681, beside the **0.689** recorded here for annual rather than the **0.864** for monthly, so
the failures are close to what this spec already says annual produces.

**The reporting run becomes monthly**, with annual retained as a reported contrast. Fixing 365
had a real reason, that holding the base learners fixed inside each reported year keeps the
per-year split clean, but it buys that clarity by building the confound into the instrument:
annual measures calibration failure and staleness at once, and this phase puts staleness an
order of magnitude ahead (+0.18 against +0.019).

**Nothing in the gate is loosened**: the band, the 5% clamp gate and the +0.03 worst-year bar
all stand, and the cadence is what gets fixed instead.

**Measured the same day, and the null does not survive it.** At a monthly refit on
`EXTENDED_SPAN` the baseline covers 0.8517 on NL [0.842, 0.861] and 0.8619 on BE [0.853, 0.871],
so the precondition passes and the arms have a reference. The baseline worst year is 2021 at
0.712 NL and 0.701 BE, and the composed arm adds **+0.146 NL and +0.150 BE** at +5.3% and +5.7%
width, clamping 4.0% and 3.2%: all three thresholds, both zones, where the recorded run read
+0.019 and nothing. **ACI alone does not**, clamping 8.4% and 9.4%. Weights alone clears the
thresholds at lower width and is still not the headline: its worst year ends outside the band
(0.794 NL, 0.782 BE), and the composed arm is the only one that returns it (0.858, 0.851). Numbers in
[studies/drift-robust-conformal](../studies/drift-robust-conformal.md).

**Re-scored on the corrected reporting run**, same thresholds:

- [x] Worst-year coverage up at least 0.03: **passes**, +0.146 NL and +0.150 BE on the composed arm, where the superseded run read +0.019 and nothing
- [x] Median width rises by less than 10%: +5.3% NL and +5.7% BE composed, and this time not trivially, since there was coverage to buy
- [!] Clamp binding under 5%: **composed passes** (4.0% NL, 3.2% BE), **ACI alone fails** (8.4%, 9.4%), so the composition is what the result argues for rather than ACI
- [!] The identity holds and the bound applies: identity holds (realized gap 0.00014 NL, 0.00048 BE); neither adaptive run is clamp-free, so Proposition 4.1 applies to neither
- [x] Bitwise reproduction on a second run: **identical**, all 18 reported result lines across both zones, four arms and the two identity runs
- [!] Adoption: **not taken.** Thresholds met, default unchanged: the result is conditional on a monthly refit only the evaluation harness performs. See Decisions
## Out of scope

- **Reweighting the R2.2 residual bank.** The same decay weights apply to the
  residual-path bootstrap, which currently resamples uniformly over the whole
  calibration history and inherits stale regimes with no decay
  ([residual-path-bootstrap](../decisions/residual-path-bootstrap.md) records this).
  It is the natural follow-on and it is a scenario-layer change, so it is not smuggled
  into a forecaster phase.
- **Conditional coverage guarantees.** Neither construction provides one. ACI's
  guarantee is long-run marginal; the weighted one is marginal with a gap term. Per-hour
  coverage stays a measured constraint, not a guarantee.
- **The nonexchangeable full-conformal and jackknife+ variants** (Theorems 2b and 2c)
  and nonexchangeable cross-conformal. Split and CQR are what this project uses.
- **The randomization / swap step** for algorithms that treat data points
  asymmetrically. The base learners here are prefit on a disjoint earlier block and are
  never refit during calibration, so the symmetric case applies.
- **DtACI, AgACI, and other step-size-free variants.** A single $\gamma$ chosen on
  synthetic drift is the scope; removing the knob is a further phase.
- **Automatic triggering in the serving path.** R2.1b's out-of-scope note stands: the
  monitor classifies and logs, and wiring adaptation into live serving is a separate
  reliability question.
- **Multi-horizon or intraday ACI.** One update per day-ahead delivery day.

## Decisions

- **Phase ID: R2.1g, continuing the letter suffix.** *Proposed:* yes. Every forecaster
  phase since R2.1 carries one, including R2.1f, which was renumbered from a plain R2.9
  precisely so the forecaster's phases read as one sequence. A plain number would say
  this phase is a different capability, and it is not: it is the same forecaster with a
  different calibration step.
  **Resolved:** R2.1g (2026-08-31).
- **The formulation delta stays inside §R2.1 rather than opening a new section.**
  *Proposed:* yes. R2.1e set the precedent for a substantial construction change landing
  as labelled paragraphs inside §R2.1, and the file's sections track optimizer-facing
  subjects (forecast, scenarios, two-stage, bid curve). A separate section would imply a
  separate object, and this is the same object calibrated differently.
  **Resolved:** inside §R2.1 (2026-08-31).
- **Extend the price span back to 2019-01-01.** *Proposed:* yes. The phase's motivating
  evidence is the 2021 crisis ramp, and under the R2.1d layout all of 2021 is
  training-only, so the worst-calibrated year is the one no gate can score. Fetching two
  more years makes 2021 a reporting year with a full 365-day window behind it. Cost is a
  larger cache and one refetch; the risk is that the published R2.1d/R2.7/R2.1f numbers
  must be shown unchanged on the original span, which is a build task above rather than
  a hazard. If the human declines, the fallback is to report 2021 as an in-selection
  sensitivity and take 2022 as the worst reporting year, which weakens the headline but
  not the method.
  **Resolved:** extend to 2019-01-01 (2026-08-31). The fallback is not taken; the
  original-span reproduction is the build task that keeps the published numbers honest.
- **Knobs selected on synthetic drift, with real data as a sensitivity only.**
  *Proposed:* yes. Both knobs are functions of drift rate, which can be simulated with a
  known answer, and an online method cannot be selected on gap-placed folds the way R2.1f
  selected a grid: a sequential run traverses the whole span, so there is no clean
  disjoint tuning block. Choosing on synthetic drift keeps every real day available for
  reporting and keeps the selection leakage-free by construction. The gap-placed folds
  from R2.1f are then a sensitivity check, reported and not selected on.
  **Resolved:** synthetic-drift selection (2026-08-31).
- **The ACI update is batched per delivery day.** *Proposed:* yes, with the re-derivation
  as a build task and a property test, not an assertion. Twenty-four hourly updates on
  outcomes that all settle at once would model an information arrival that does not
  happen, and the day is already the project's unit of effective sample size.
  **Resolved:** day-batched (2026-08-31), conditional on the re-derivation below
  holding; if it does not, the update falls back to 24 sequential per-hour steps.
- **The clamp is `(0.01, 0.5)` and voids the guarantee while it binds.** *Proposed:* yes,
  with the binding rate gated at 5%. The alternative, emitting an unbounded interval, is
  unusable downstream: the R2.2 bootstrap would draw from an infinite support. The honest
  treatment is to clamp, count, publish the count, and refuse to adopt a saturated arm.
  **Resolved:** clamp `(0.01, 0.5)`, binding rate gated at 5% (2026-08-31).
  **Amended during implementation (2026-08-31):** the proposal understated the cost. A
  property test on adversarial sequences showed that clamping removes the saturation
  feedback Lemma 4.1 rests on, so the iterate can diverge and the published bound does
  not return when the clamp stops binding. The clamp and its 5% gate stand; what changed
  is that the gate now reads the exact telescoping identity, which survives clamping,
  rather than asserting a bound that does not.
- **Which cadence is the reporting run, now that the live module has actually run?**
  *Proposed:* monthly. The approved parameter was annual, the recorded numbers were monthly,
  and the outage kept the module from running, so nobody noticed. **Resolved:** monthly,
  annual kept as a contrast (2026-09-03); see the amendment above.
- **The thresholds are met on the corrected run. Adopt?** *Proposed:* not yet.
  The composed arm clears worst-year coverage, width and the clamp gate in both zones, which
  is the adoption condition as written. What the condition did not anticipate is that the
  result is conditional on a refit cadence: `refit_every_days` lives in the evaluation
  harness, nothing in the serving path schedules a refit, and the same arm clamps 71.6% and
  fails outright at an annual one. Adopting would ship a default whose measured benefit rests
  on an operating discipline this repo neither implements nor enforces.
  **Resolved:** cadence first, then re-score and adopt if it still clears (2026-09-03).
- **MAPIE stays on the unweighted path.** *Proposed:* yes. Writing our own conformal step
  for the weighted case is unavoidable (MAPIE exposes no weighted quantile), but
  replacing the shipped path too would put the incumbent's numbers at the mercy of a new
  implementation. Golden oracle 1 binds the two, so a divergence fails loudly instead of
  drifting.
  **Resolved:** MAPIE keeps the unweighted path (2026-08-31).
- **Adoption thresholds: +0.03 worst-year coverage, under 10% calm-year median width.**
  *Proposed:* these numbers, for the human to accept or move. They are the first
  quantities in this spec that are a judgment rather than a derivation. The 0.03 is set
  so a change must be larger than the 0.02 the existing rolling recalibration already
  delivers; the 10% is set well below the 38% width that recalibration costs, because a
  method that buys coverage as expensively as the heuristic it replaces is not an
  improvement.
  **Resolved:** +0.03 and 10% as proposed (2026-08-31).
- **Which side moves on the symmetric/asymmetric divergence.** *Proposed:* change the
  **code** to match §R2.1, in a separate change, not this one. The documented symmetric
  form is what the governing references state (Romano et al. via Angelopoulos & Bates for
  CQR, Barber et al. for the weighted extension), so the doc is the side that is right,
  and a weighted asymmetric variant would need its own coverage argument that no cited
  source supplies. Keeping it out of R2.1g is deliberate: it moves the shipped numbers,
  so it deserves its own gate run rather than riding along inside a phase that is already
  changing calibration. **Not resolved: this is the human's call.**
- **The incumbent-equivalent baseline is symmetric and unweighted.** *Proposed:* yes, as
  a fifth measured arm alongside the four. Without it, "weighted versus shipped" is two
  changes measured as one.
- **What happens if both arms pass.** *Proposed:* adopt the composition only if it beats
  each single arm on the worst year by more than the seed spread. Two knobs are harder to
  defend than one, and R2.1f's finding was that two zones chose different configurations,
  so a composed default needs to clear a higher bar than "not worse".
  **Resolved:** the composition must beat each single arm by more than the seed
  spread (2026-08-31).
