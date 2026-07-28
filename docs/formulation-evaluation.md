# BESS Dispatch Formulation: evaluation

*The single source of truth for how results are measured.*

Companion to [formulation.md](formulation.md) (the deterministic model) and [formulation-uncertainty.md](formulation-uncertainty.md) (the stochastic layer).
Neither section here adds a constraint, variable, or objective term.
They define **what a reported number means**: which information the decision was allowed to see, which revenue quantities are comparable, and how a value claim is scored out of sample.
Grouping them together is deliberate, because the leakage discipline in §R1.4 is what makes the §R2.5 protocols honest, and the two rot as a pair when they drift.

The findings these protocols produced are written up in [studies/](studies/).

*Assumes: [formulation.md](formulation.md) and the house notation in [Conventions](conventions.md) (grid-side power, per-unit SoC, `π / e / η / Δt`).*

GitHub renders the `$$…$$` LaTeX below. The changelog for all three files is at the end of [formulation.md](formulation.md#changelog).

---

## R1.4. Backtest semantics

*No governing reference:
walk-forward evaluation and the decision-time (no-look-ahead) information set are standard time-series backtesting practice, not a technique traceable to a single source.
See [references.md: R1.4](references.md#r14-backtest-walk-forward-baselines-sanity-band) for domain-context pointers;
the leakage-control machinery specific to a fitted model (purged CV, embargo) is deferred to R2.1.*

This section adds **no constraints, variables, or objective terms**.
It defines the three revenue quantities the backtest ([specs/R1.4a-backtest.md](specs/R1.4a-backtest.md)) reports and the leakage discipline they obey;
all built from the *existing* R1.1/R1.2 optimizer.
If code and this section disagree, this governs.

### The information set (gate closure)

The whole day-ahead block for delivery day $d$ is committed at a single gate (≈12:00 CET on $d-1$).
So at decision time the agent knows **all** of day $d$'s prices, but **none** of day $d+1$'s.
Write $\Pi_d$ for the price vector of day $d$.
The decision for day $d$ may depend on $\Pi_d$ and on the SoC carried in from $d-1$, and on **nothing from $d'>d$**: this is the leakage boundary (gate C; the gates are lettered in [specs/R1.4a-backtest.md](specs/R1.4a-backtest.md)).

### Three revenue quantities

Let $V(\boldsymbol\pi; e_0,e^{\mathrm{tgt}})$ be the optimal objective of the R1.1/R1.2 MILP on price vector $\boldsymbol\pi$ with the given SoC endpoints, over a horizon that starts and ends empty unless stated.
All three quantities are **net of degradation**: each is the R1.2 objective (grid-side cash flow minus $\sum_t D_t$), so when wear is priced the greedy floor is scored net of its own $D_t$ too, on the same $\tau_{\max}$ basis, keeping the ordering below valid (with no degradation, $D_t\equiv 0$ and each reduces to gross arbitrage).

- **Perfect-foresight ceiling** $V^\star$:
 one **full-horizon** solve over the entire concatenated series with $e_0=e_{\text{end}}=0$ and SoC free to carry **across** day boundaries.
    This is the theoretical maximum; nothing can exceed it.
- **Rolling deployable value**
 $V^{\mathrm{roll}}=\sum_d V(\Pi_d; 0,0)$: **per-day** solves, each starting and ending empty.
 In a *deterministic* day-ahead setting the agent has no information about $\Pi_{d+1}$ at the day-$d$ gate, so it has no basis to carry SoC overnight;
 per-day independence (terminal SoC $=0$) is the honest myopic model.
    Each day's solve is still **intraday-optimal**.
- **Greedy floor** $V^{\mathrm{greedy}}$:
    a percentile rule (charge below the day's 20th price-percentile, discharge above the 80th), defined fully in the spec.
    A feasible but suboptimal policy;
    it ignores the round-trip-efficiency breakeven, so it can even trade at a loss.

**Day boundary (UTC).**
A "day" here is a **UTC calendar day** (00:00–24:00 UTC): the engine windows the series by calendar-day grouping, and the rolling solves empty at each UTC midnight.
That is 1 h (CET) or 2 h (CEST) after the local BE/NL market midnight, so the boundary falls in the calm early-morning hours where the battery is naturally near-empty, not mid-day.
UTC alignment keeps every window a clean 24 periods (a local-day grouping would give ragged 23/25-hour windows at the DST transitions) and matches the UTC time convention ([conventions.md](conventions.md));
the resulting 1-to-2-hour offset from the market day is immaterial to a rolling backtest that empties at each boundary.

### Provable ordering (a correctness gate)

$$\boxed{ V^{\mathrm{greedy}} \le V^{\mathrm{roll}} \le V^\star, \qquad 0 \le V^{\mathrm{roll}}. }$$

![Three nested revenue levels on one axis: zero, the greedy floor, the rolling per-day deployable value, and the perfect-foresight ceiling. The greedy-to-rolling gap is the value of optimization; the rolling-to-ceiling gap is cross-day arbitrage, small for a short-duration asset. The reported headline pairs both levels against the ceiling, since rolling-over-ceiling alone saturates near 1.](figures/backtest-bounds.svg)

- $V^{\mathrm{roll}}\le V^\star$:
 the rolling schedule returns to $e=0$ each midnight, so it is a **feasible** trajectory for the full-horizon problem, the ceiling can only do at least as well.
- $V^{\mathrm{greedy}}\le V^{\mathrm{roll}}$:
    the greedy schedule is feasible for each day's MILP (it too ends the day empty), and the per-day MILP is optimal over all such schedules.
- $0 \le V^{\mathrm{roll}}$:
 idle is feasible in every per-day solve, so each *optimal* per-day value is non-negative (likewise $0 \le V^\star$).
 $V^{\mathrm{greedy}}\ge 0$ is **not** guaranteed: greedy can trade at a loss, so the zero floor bounds the optimal quantities only.

The two gaps in the ladder measure different things:

- **$V^{\mathrm{roll}}-V^{\mathrm{greedy}}$** is the value of **optimization** over a naive percentile heuristic.
    Both agents empty each day, so this is a clean same-horizon contrast; it is the informative R1 comparison.
- **$V^\star-V^{\mathrm{roll}}$** is the value of **cross-day foresight**:
 overnight-carry revenue a deterministic day-ahead agent cannot reach, having no information about $\Pi_{d+1}$ at the day-$d$ gate.
 For a short-duration asset this gap is small by physics (a battery that empties nightly has little to carry overnight), so $V^{\mathrm{roll}}$ sits just under $V^\star$.
    It widens with storage duration (a 1-hour asset shows almost none; a 4-hour asset shows more).

This overnight gap is an upper bound on what any carry strategy could add; it is **not** what R2 targets.
R2's payoff is handling price **uncertainty at decision time**, measured by the value of the stochastic solution (VSS) in R2.3, a quantity distinct from the deterministic overnight gap that does not vanish when that gap does.

**Headline metric.**
Report $V^{\mathrm{greedy}}/V^\star$ and $V^{\mathrm{roll}}/V^\star$ together (heuristic and optimal, as % of perfect foresight).
$V^{\mathrm{roll}}/V^\star$ alone saturates near 1 for a short-duration asset and cannot discriminate; the greedy-to-rolling gap carries the R1 signal, and VSS (R2.3) carries the R2 signal.
Because these ratios move with storage duration, they are reported across {1h, 2h, 4h} rather than for a single asset ([ADR-0022](decisions/0022-storage-duration-reported-axis.md)).

### Sanity band (gate D)

The annualized ceiling per MWh-installed must sit inside a band **derived from the fixture's own price statistics** (not hard-coded):
$V^\star_{\text{annual}}/E_{\text{usable}} \approx c\cdot\overline{\text{spread}}_{\text{daily}}$, where $\overline{\text{spread}}_{\text{daily}}$ is the mean over days of that day's max-minus-min price and $c=\eta^{rt} (\text{cycles/day})\cdot 365$ is recomputed from the spec.
($E_{\text{usable}}$ already divides the left side, so it must not reappear in $c$; both sides are €/MWh-installed per year.)
A result above the ceiling band is a leakage red flag, not alpha.

---

## R2.5. Value evaluation hardening (evaluation semantics; no optimizer change)

*No governing reference:
the quantities below are evaluation protocols over the existing §R2.3 program (Birge-Louveaux metrics under the §R1.4 leakage discipline) plus the standard quantile (pinball) loss.
See [references.md: R2.3](references.md#r23-risk-aware-two-stage-dispatch--intraday-recourse) for the underlying machinery.*

This section adds **no constraints, variables, or objective terms**.
It defines the three quantities the evaluation layer ([specs/R2.5-value-evaluation.md](specs/R2.5-value-evaluation.md)) reports over the existing optimizer;
if code and this section disagree, this governs.

### Per-window out-of-sample VSS (a distribution, not a number)

R2.3's gate measured VSS $>0$ out-of-sample on a *designed* value-generating instance.
This protocol asks whether that value is a property of the market rather than of the design, by repeating the ADR-0021 measurement over arbitrary real delivery windows.

A **window** $w$ is a UTC calendar day (the §R1.4 boundary) with realized price path $y^{(w)}$.
Its **training scenario set** $S_w$ is $n$ equiprobable day-paths drawn with replacement from the $H$ complete days strictly before $w$ (an empirical bootstrap over recent day shapes; the §R1.4 information set, so nothing at or after $w$ enters).
Fit both first-stage commitments on $S_w$: $g^{RP}$ (risk-neutral two-stage optimum) and $g^{EV}$ (deterministic solve at the mean path $\bar\pi_w$ of $S_w$).
Score each commitment fixed, with optimal within-budget recourse, on the single realized path (an $S=1$ evaluation set), the day-ahead leg settling at $\bar\pi_w$ for both, exactly the ADR-0021 protocol:

$$\boxed{ \mathrm{VSS}_w = v_w\bigl(g^{RP}\bigr) - v_w\bigl(g^{EV}\bigr), }$$

where $v_w(g)$ is that held-out score. $\mathrm{VSS}_w$ carries no sign guarantee (out-of-sample, per ADR-0021); the reported object is the **empirical distribution** $\{\mathrm{VSS}_w\}$ over all windows with enough history (median, quartiles, share $>0$), never a single number.

### Forecast value (euros, not statistics)

The same fixed-commitment scoring, applied to two scenario sets that differ **only in the forecast** feeding the §R2.2 residual-path bootstrap: the R2.1 conformal forecast (its point path and residual history) versus a seasonal-naive forecast (same hour one week prior, with its own residual history).
With $g^{\text{conf}}$ and $g^{\text{naive}}$ the risk-neutral two-stage commitments fit on the respective sets,

$$\boxed{ \mathrm{FV} = v\bigl(g^{\text{conf}}\bigr) - v\bigl(g^{\text{naive}}\bigr). }$$

FV is distinct from EV/EEV (which use one set's mean rather than contrasting forecasters) and is **reported with provenance, not asserted positive**: whether forecast skill converts to dispatch euros on a given window is the finding the protocol exists to measure.
Like the VSS above, FV is reported **per window as a distribution** (median, quartiles, share $>0$) over all scoreable UTC days, with the forecaster refit walk-forward (fit strictly before each block of windows); a single window's sign is noise, the distribution's center is the finding.

### Pinball (quantile) loss and skill

For target $y$, quantile prediction $\hat q$ at level $\tau\in(0,1)$:

$$\boxed{ \ell_\tau(y,\hat q) = \max\{\tau (y-\hat q),\ (\tau-1)(y-\hat q)\} }$$

averaged over a §R1.4-style walk-forward test block, reported at the R2.1 interval edges $\tau=\alpha/2,\ 1-\alpha/2$.
The **skill ratio** divides the conformal forecaster's loss by the seasonal-naive predictor's at the same $\tau$; below 1 means skill.
Sanity identity: at $\tau=\tfrac12$ the pinball loss equals half the mean absolute error.
This gives R2.1 an *accuracy* number beside its *calibration* (coverage) number; the two are independent axes (a wide, well-calibrated interval has coverage without skill).

**Considered but out of scope:** CRPS and full-distribution scores (pinball at the shipped interval edges matches what R2.1 emits); formal significance testing of forecast-accuracy differences (Diebold-Mariano); retraining-cadence optimization (§R2.1b owns the drift decision); an intraday/imbalance settlement model (the scoring reuses §R2.3's two-price construction).
