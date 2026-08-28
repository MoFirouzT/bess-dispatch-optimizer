# BESS Dispatch Formulation: uncertainty

*The single source of truth for how the project represents and optimizes under price uncertainty.*

Companion to [formulation.md](formulation.md), which holds the preamble, the house conventions, the deterministic model, and the duals read off it.
This file holds the forecast, the scenario representation, the two-stage program, and the bid curve: everything whose subject is *not knowing the price*.
Measurement protocols live in [formulation-evaluation.md](formulation-evaluation.md).
The same rules apply here: specs, the README, and ADRs **point here**, they never restate equations.

*Assumes: [formulation.md](formulation.md) and the house notation in [Conventions](conventions.md) (grid-side power, per-unit SoC, `π / e / η / Δt`).
The R1.1 dispatch model is reused unchanged as the per-scenario physics throughout; battery and power-market terms are defined in the [glossary](glossary.md).*

GitHub renders the `$$…$$` LaTeX below. The changelog for all three files is at the end of [formulation.md](formulation.md#changelog).

---

## R2.1. Probabilistic price forecast (conformal intervals; no optimizer change)

*Governing reference: Angelopoulos & Bates, *A Gentle Introduction to Conformal Prediction* (see [`references.md`](references.md): R2.1). This section summarizes only the coverage guarantee the forecaster relies on; it adds **no constraint, variable, or objective term** to the dispatch MILP above.*

R2.1 replaces a point price $\pi_t$ with an **interval** $[\underline{\pi}_t, \overline{\pi}_t]$ carrying a distribution-free coverage guarantee, the uncertainty input the R2.2+ stochastic layer samples. Let a base regressor be fit on a *proper-training* split and a disjoint *calibration* split $\mathcal C$ (of size $n$) held out, with target miscoverage $\alpha$ (so $\text{confidence} = 1-\alpha$).

*Notation reconciled to house style.* The reference writes the interval bounds as generic lower/upper limits and the conformal margin as $\hat q$. Here the bounds take the price symbol $\pi$ ($\underline{\pi}_t, \overline{\pi}_t$) and the margin is $\hat s$, because $\hat q_{\alpha/2}$ already names the quantile regressors below and $u_t$ is the R1.1 binary.

**Split conformal.** With calibration residuals $R_i = |y_i - \hat\mu(x_i)|$ for $i\in\mathcal C$, let $\hat s$ be the $\lceil(1-\alpha)(n+1)\rceil/n$ empirical quantile of $\{R_i\}$. The interval $\hat\mu(x)\pm\hat s$ then satisfies the **marginal coverage** bound

$$ \boxed{ \mathbb P\big(y \in [\hat\mu(x)-\hat s,\ \hat\mu(x)+\hat s]\big) \ \ge\ 1-\alpha } $$

for exchangeable data, in finite samples, *independent of the model's accuracy*: the property the coverage gate checks empirically. Width is **constant** in $x$.

**CQR (the default; [CQR over split conformal](decisions/cqr-over-split-conformal.md)).** Replace the point model with lower/upper quantile regressors $\hat q_{\alpha/2}, \hat q_{1-\alpha/2}$; conformalize on $\mathcal C$ with the signed score $E_i = \max\{\hat q_{\alpha/2}(x_i)-y_i,\ y_i-\hat q_{1-\alpha/2}(x_i)\}$ and its $(1-\alpha)$ quantile $\hat s$, giving $[\hat q_{\alpha/2}(x)-\hat s,\ \hat q_{1-\alpha/2}(x)+\hat s]$. Same marginal guarantee; width is now **input-adaptive**, which matters because day-ahead prices are heteroscedastic (volatile peaks, calm nights).

**Gate (statistical, not a hand-solved oracle).** The claim is that empirical coverage under the R1.4 walk-forward lies within $\pm 0.05$ of nominal (so $0.9 \Rightarrow [0.85, 0.95]$). Because coverage is a *sampling statistic* whose indicators cluster within a day, that claim is tested by a **day-block bootstrap interval** rather than by a point estimate: the gate fails only when the whole interval falls outside the band, that is, only when the data can rule the claim out ([R2.1d](specs/forecaster-evaluation.md)). Intervals obey $\underline{\pi}_t \le \hat\mu_t \le \overline{\pi}_t$; features are strictly pre-gate-closure (no leakage). Coverage is gated alongside **sharpness** (pinball loss against a seasonal-naive baseline), since coverage alone is satisfiable by an arbitrarily wide interval. **Exchangeability** is the critical assumption; a price-distribution shift breaks it, which is exactly what the R2.1b drift monitor and the 7-day rolling recalibration exist to manage.

**Normalized target ([R2.1e](specs/target-normalization.md)).** Optionally the learner is fit not on $\pi_t$ but on the standardized target $z_t = (\pi_t - m_t)/s_t$, where the level $m_t$ and scale $s_t$ are the mean and standard deviation of a trailing window ending at $t - 24 \text{h}$ (so both are known at gate closure, exactly like the lags). Predictions and both interval bounds are mapped back by $\pi = m_t + s_t z$. Because $m_t, s_t$ are **known constants at prediction time** and $s_t > 0$, that map is a strictly increasing affine bijection, so coverage transfers point by point:

$$ \mathbb P\big(\pi \in [m_t + s_t\underline{z},\ m_t + s_t\overline{z}]\big)  =  \mathbb P\big(z \in [\underline{z}, \overline{z}]\big)  \ge  1-\alpha $$

The guarantee above is therefore **inherited, not re-derived**. What changes is that interval width in price space is proportional to $s_t$, so it widens in volatile periods without any change to the conformal machinery: the locally-weighted (normalized-nonconformity) construction, aimed at the *conditional* miscalibration that the marginal guarantee permits. De-levelling is **additive**, never a log or ratio, because a material share of hours clear at or below zero.

**Considered but out of scope:** conditional (per-$x$) coverage guarantees (conformal gives only marginal); cross-conformal / jackknife+ (heavier, not needed at this data scale); adaptive conformal for distribution shift (ACI); noted for R2.1b, not built here.

---

## R2.2. Scenario generation + reduction (uncertainty representation; no optimizer change)

*Governing reference: Dupačová, Gröwe-Kuska & Römisch (2003) and Heitsch & Römisch (2003) for probability-metric scenario reduction; King & Wallace, *Modeling with Stochastic Programming*, for generation framing (see [`references.md`](references.md): R2.2). This section summarizes only the discrete construction R2.2 builds; it adds **no constraint, variable, or objective term** to the dispatch MILP above. The set it defines is the input the R2.3 stochastic program will optimize over.*

R2.2 turns the R2.1 interval forecast into a **discrete probability distribution over price paths**: a scenario set $\{(\pi^{(s)}, p_s)\}_{s=1}^{S}$ where each $\pi^{(s)} = (\pi^{(s)}_1,\dots,\pi^{(s)}_T)$ is a full-horizon price path (house schema: €/MWh, grid-side, UTC hourly) and $p_s \ge 0$, $\sum_s p_s = 1$.

**Generation (residual-path bootstrap; [the residual-path bootstrap](decisions/residual-path-bootstrap.md)).** Given the point forecast $\hat\mu = (\hat\mu_1,\dots,\hat\mu_T)$ and the forecaster's historical whole-day residual vectors $\{r^{(m)}\}_{m=1}^{M}$ (each $r^{(m)} = y^{(m)} - \hat\mu^{(m)}$, an actual-minus-forecast error path from the calibration history), draw $n$ indices $j_1,\dots,j_n$ uniformly with replacement and set $\pi^{(s)} = \hat\mu + r^{(j_s)}$, equiprobable $p_s = 1/n$. Resampling *whole vectors* (not per-hour draws) preserves the empirical intra-day correlation of forecast errors, so the paths carry realistic peak/trough shape rather than 24 independent wiggles.

**Reduction distance.** For a fine distribution $P$ (support $\{\pi^{(i)}\}$, mass $p_i$) and a coarse one $Q$ supported on a *subset* of $P$'s atoms (the kept scenarios), the Wasserstein-$\ell$ (Kantorovich) distance under optimal redistribution has a closed form: each deleted atom's mass moves to its nearest kept atom, giving

$$ \boxed{ D_\ell(P, Q) = \Big(\sum_{i \in J} p_i \min_{j \notin J} \lVert \pi^{(i)} - \pi^{(j)} \rVert^{\ell}\Big)^{1/\ell} }, $$

where $J$ is the deleted index set and $\lVert\cdot\rVert$ is the Euclidean ground metric on paths (default $\ell = 2$). The kept atom $j$ receives $q_j = p_j + \sum_{i \in J: j = \arg\min_{k \notin J}\lVert\pi^{(i)}-\pi^{(k)}\rVert} p_i$, so $Q$ stays a valid probability measure. (The same assignment-cost expression, with representatives that need not be original atoms, scores the k-means baseline whose centroids are not atoms; there it is an upper bound on the true $W_\ell$, used consistently so the two methods compare fairly.)

**Fast forward selection ([forward selection over k-means](decisions/forward-selection-over-kmeans.md)).** Choosing the size-$k$ subset that minimizes $D_\ell$ is combinatorial; forward selection is the standard greedy surrogate. Start with all atoms deleted; repeatedly add to the kept set the atom $u$ that most reduces $D_\ell$ (equivalently, minimizes $\sum_i p_i \min_{j \in \text{kept}\cup\{u\}} \lVert\pi^{(i)}-\pi^{(j)}\rVert^{\ell}$), until $|\text{kept}| = k$; then redistribute as above. k-means on the paths (centroids as representatives, cluster mass as probability) is the pragmatic baseline the gate compares against.

**Gate (partly exact, partly statistical).** Reduction to a size-$S$ subset is the identity ($D = 0$); a small hand-built set has an exact $D_\ell$ and forward-selection choice (golden oracle). Beyond that the gate is behavioral: $D_\ell$ is non-increasing as $k$ grows; the forward-selected subset's $D_\ell$ is no larger than a random subset of equal size (the reducer does real work); the reduced measure conserves mass. Whether a reduced set preserves the eventual *dispatch value* is an R2.3 check (it needs the stochastic objective), deferred honestly rather than asserted here.

**Considered but out of scope:** moment matching and copula generation (alternative generators, not built); ARIMA/GARCH parametric generation on raw prices (a second generator path, deferred); multistage / nested scenario trees (R2.2 is a single-stage day-ahead fan; tree structure belongs with R2.3 recourse); Fortet-Mourier and other probability metrics (the stability bound here uses Kantorovich).

---

## R2.3. Risk-aware two-stage dispatch + intraday recourse (optimizer delta)

*Governing reference: Birge & Louveaux, *Introduction to Stochastic Programming* (two-stage recourse, VSS/EVPI); subordinate-authoritative Shapiro, Dentcheva & Ruszczyński (CVaR) and Rawlings, Mayne & Diehl (receding-horizon MPC). See [references.md: R2.3](references.md#r23-risk-aware-two-stage-dispatch--intraday-recourse). This is the first Release-2 section that **changes the optimizer**: it adds recourse variables, a CVaR risk term, and a non-anticipativity structure over the R1.1 physics, which is reused unchanged as the per-scenario second-stage model.*

R2.3 optimizes dispatch over R2.2's scenario set $\{(\pi^{(s)}, p_s)\}_{s=1}^{S}$ instead of a single price path, and reports the **value of the stochastic solution (VSS)** so the layer is measured, not assumed ([stochastic value requires risk or recourse](decisions/stochastic-value-requires-risk-or-recourse.md)).

**The VSS-collapse trap (the design driver).** If the whole 24-hour dispatch is one here-and-now decision $x$, the risk-neutral stochastic objective is $\max_x \mathbb E_s[\pi^{(s)}\cdot x] = \bar\pi\cdot x$ (with $\bar\pi = \sum_s p_s \pi^{(s)}$), *identical* to the mean-value problem, so VSS $= 0$: linear objective $\times$ price-independent feasible set. R2.3 escapes it two ways ([the two-stage design](decisions/risk-aware-two-stage-design.md), [the CVaR risk model](decisions/risk-aware-two-stage-design.md)): genuine, *limited* recourse; and a risk term that is not linear in the outcomes.

### Two-stage structure (day-ahead commitment + intraday recourse)

The house R1.1 net-export power is $g_t \equiv p^{dis}_t - p^{ch}_t$ (grid-side, MW). A **first-stage** day-ahead schedule $g^{DA}$ is committed before the intraday price is known; it is itself R1.1-feasible (its own SoC trajectory $e^{DA}$). A **second-stage** per-scenario dispatch $g^{(s)}$ re-optimizes against the realized price $\pi^{(s)}$, also R1.1-feasible (SoC balance, bounds, mutual-exclusion binary $u^{(s)}_t$, ramp, terminal), and is tied to the commitment by a **recourse budget**:

$$\boxed{ \lvert g^{(s)}_t - g^{DA}_t\rvert \le \Delta\bar P = \rho \bar P \qquad \forall t,\ \forall s, \qquad \rho \in [0,1]. }$$

$g^{DA}$ is **non-anticipative** (one schedule, shared across all scenarios); each $g^{(s)}$ adapts within $\Delta\bar P$ of it. Settlement: the day-ahead volume clears at the known day-ahead price $\pi^{DA}$ (default $\pi^{DA}=\bar\pi$), the intraday deviation at the realized price:

$$\boxed{ \text{profit}_s = \sum_{t}\Delta t \big[\pi^{DA}_t g^{DA}_t + \pi^{(s)}_t (g^{(s)}_t - g^{DA}_t)\big]. }$$

With $\pi^{DA}=\bar\pi$ this reduces to $\mathbb E_s[\text{profit}_s] = \mathbb E_s\big[\sum_t\Delta t \pi^{(s)}_t g^{(s)}_t\big]$, so $g^{DA}$ enters **only** through the budget constraint: it is the central commitment each scenario deviates from within $\Delta\bar P$. This is what makes the mean schedule a *suboptimal center* for a spread of scenarios, so VSS $> 0$ at intermediate $\rho$; the two limits $\rho\to 0$ (no recourse) and $\rho\to 1$ (unlimited recourse) both collapse to VSS $= 0$, a sanity check the gate uses.

### Risk-aware objective (CVaR mean-risk; Rockafellar-Uryasev)

Let $L_s = - \text{profit}_s$, tail level $\alpha\in(0,1)$, risk weight $\lambda\in[0,1]$. Introduce the VaR auxiliary $\eta$ and tail slacks $z_s\ge 0$:

$$\boxed{ \max_{g^{DA}, g^{(s)}, \eta, z_s} \ (1-\lambda)\sum_s p_s \text{profit}_s - \lambda\underbrace{\Big(\eta + \tfrac{1}{1-\alpha}\sum_s p_s z_s\Big)}_{\text{CVaR}_\alpha(L)} \quad\text{s.t.}\quad z_s \ge L_s - \eta,\ \ z_s\ge 0. }$$

The bracket is $\text{CVaR}_\alpha$ of the loss; at the optimum $\eta$ recovers the Value-at-Risk. $\lambda=0$ is the risk-neutral expectation (the RP objective below); sweeping $\lambda$ traces the **mean-CVaR frontier**. Every term is LP-representable, so the program stays a MILP (the only integrality is the per-scenario $u^{(s)}_t$) solved by HiGHS, no new dependency.

### Recourse realization (receding-horizon MPC)

The deployable form of the recourse is receding-horizon control: execute the committed action, then at each step re-solve the *remaining* horizon at the updated (realized) prices, carrying SoC as the linking state ([the recourse and out-of-sample protocol](decisions/risk-aware-two-stage-design.md)). Plant model = SoC balance (1); disturbance = the price forecast; the intraday `dt` may refine to 15-minute while day-ahead stays hourly (`dt` is already a per-solve argument). This is the operational policy whose expected value the two-stage program above anticipates.

### Decision-value metrics (Birge-Louveaux), tied to R1.4

- **EV**: mean-value solve at $\bar\pi$, first-stage $\bar g$.
- **RP**: recourse-problem value (the risk-neutral two-stage optimum, $\lambda=0$).
- **EEV**: fix $g^{DA}=\bar g$, evaluate its expected value with optimal within-budget recourse.
- **WS**: wait-and-see $=\sum_s p_s V^\star(\pi^{(s)})$, the scenario-averaged perfect-foresight value; this is R1.4's ceiling averaged over scenarios (the $\rho\to 1$ / unbudgeted limit).
- **VSS** $=\text{RP}-\text{EEV}\ge 0$; **EVPI** $=\text{WS}-\text{RP}\ge 0$.

**VSS is the R2 value metric, distinct from R1.4's overnight gap.** R1.4's $V^\star-V^{\mathrm{roll}}$ measures cross-day foresight under *certainty* (small for a short-duration asset, since prices are already known at the day-ahead gate); VSS measures the payoff of *handling uncertainty at decision time*, and can be positive even when that overnight gap is near zero. R1.4 is the deterministic-ceiling story; VSS is the stochastic-value story this section exists to measure.

Ordering (a correctness gate, extending R1.4's $V^{\mathrm{greedy}}\le V^{\mathrm{roll}}\le V^\star$):

$$\boxed{ \text{EEV} \le \text{RP} \le \text{WS}. }$$

The gate is: measured VSS $> 0$ **out-of-sample** on the designed value-generating instance (held-out realized paths, R1.4 leakage discipline; [the recourse and out-of-sample protocol](decisions/risk-aware-two-stage-design.md)); the CVaR-averse solution reduces tail loss versus the risk-neutral one under $\pm 10\%$ price error; and the VSS $=0$ collapse is reproduced exactly at the $\rho$-limits (a golden oracle, proving the trap is understood, not papered over).

**Considered but out of scope:** the Bertsimas-Sim $\Gamma$-budget robust counterpart (an alternative to CVaR, noted not built; [the CVaR risk model](decisions/risk-aware-two-stage-design.md)); hard chance constraints as a separate mechanism (the soft CVaR objective stands in); multistage ($>2$-stage) trees; Benders / L-shaped decomposition (R2.4 / optional Julia); an explicit intraday order-book or imbalance-settlement market model (the recourse re-trades against a realized price, it does not model market microstructure; R3 scope).

**Forecast-value baseline.** The metrics above measure the value of *stochastic optimization* (VSS), but not the value of *forecast skill*: R2.1/R2.2 score the forecaster statistically, and R2.3 optimizes over whatever scenario set it is handed. The baseline that closes that loop, running the same two-stage dispatch on scenarios from a seasonal-naive forecast versus the R2.1 conformal forecast and comparing realized-price profit in euros, is built in §R2.5 below.

---

## R2.6. Price-contingent day-ahead bid curves (optimizer delta)

*Governing reference: pending verification (see [references.md](references.md): R2.6).
Day-ahead bidding under price uncertainty is the one genuinely new piece of theory here, the candidate sources are named but unverified, and nothing below relies on them.
The R1.1 physics, the §R2.3 recourse budget, and the §R2.3 CVaR objective are reused unchanged.*

R2.6 changes what the first stage *is*. §R2.3 commits one day-ahead schedule shared by every scenario, but a day-ahead auction does not accept schedules: at gate closure the clearing price is unknown, so a participant submits, per hour, a monotone set of (price, quantity) pairs, and the auction resolves the dispatch afterwards. This is a **price-taker** construction and has nothing to do with reflexivity ([§R1.1 modeling notes](formulation.md#modeling-notes)): it handles price *uncertainty*, not price *impact*.

### The bid curve as a measurability condition

Index the first stage by scenario, $g^{DA,(s)}$, each branch R1.1-feasible in its own right with its own SoC trajectory $e^{DA,(s)}$ (whichever branch clears must be physically deliverable). Two constraint families, imposed **within each hour** $t$, make the family a submittable curve:

$$\boxed{ \pi^{(s)}_t \le \pi^{(s')}_t \implies g^{DA,(s)}_t \le g^{DA,(s')}_t \quad (\text{monotone}), \qquad \pi^{(s)}_t = \pi^{(s')}_t \implies g^{DA,(s)}_t = g^{DA,(s')}_t \quad (\text{ties}). }$$

Together they say the map $\pi^{(s)}_t \mapsto g^{DA,(s)}_t$ is single-valued and nondecreasing, so there exists a nondecreasing $q_t$ with $g^{DA,(s)}_t = q_t(\pi^{(s)}_t)$ on the scenario support. **That $q_t$ is the submitted curve**, and what it encodes is that the commitment is measurable with respect to hour $t$'s clearing price *alone*. Drop the tie family and the program reads the rest of the path through prices the auction cannot tell apart, which is anticipativity wearing a bid curve's name. §R2.3's shared schedule is the special case $q_t \equiv \text{const}$. Sorting scenarios by $\pi_t$ within each hour makes this $(S-1)T$ adjacent-pair inequalities rather than $S^2T$. Monotonicity is also an exchange rule, not only a modeling choice.

### Settlement, and why the collapse is exact

The day-ahead leg settles at the price that cleared it. R2.6 therefore reads $\pi^{(s)}$ as the uncertain **day-ahead clearing price** (in §R2.3 the same symbol plays the realized intraday price, against a separate known $\pi^{DA}$), and both legs settle there:

$$\boxed{ \text{profit}_s = \sum_t \Delta t\big[\pi^{(s)}_t g^{DA,(s)}_t + \pi^{(s)}_t\big(g^{(s)}_t - g^{DA,(s)}_t\big)\big] = \sum_t \Delta t\ \pi^{(s)}_t g^{(s)}_t. }$$

The recourse budget $\lvert g^{(s)}_t - g^{DA,(s)}_t\rvert \le \rho\bar P$ and the CVaR mean-risk objective are §R2.3's, unchanged. Since §R2.3's expectation already reduces to $\mathbb E_s\big[\sum_t \Delta t\ \pi^{(s)}_t g^{(s)}_t\big]$, the two programs **maximize the same risk-neutral objective** over feasible sets that nest, which yields two exact properties:

$$\boxed{ \text{all branches equal} \implies \text{obj}^{R2.6}_{\lambda=0} = \text{obj}^{R2.3}_{\lambda=0}, \qquad \text{obj}^{R2.6}_{\lambda=0} \ \ge\ \text{obj}^{R2.3}_{\lambda=0}. }$$

Both are golden gates. At $\lambda > 0$ the two differ **by design**: §R2.3's fixed-price day-ahead leg is a forward hedge that compresses the per-scenario profit spread, and an auction leg is not, so the identity is claimed at $\lambda = 0$ only. As in §R2.3 the commitment enters solely through the budget, so the curve's value is the value of a *better-placed centre* for the recourse to deviate from, and it must shrink as $\rho$ widens.

### Worked example (monotonicity binds)

A 2 MWh / 1 MW asset at $\eta=1$ with $e_0=e^{\mathrm{tgt}}=1$ MWh over $T=2$, so the terminal constraint reduces every feasible dispatch to $g=[a,-a]$, $a\in[-1,1]$. Two equiprobable scenarios: $\pi^{(1)}=[60,10]$ and $\pi^{(2)}=[80,500]$. Branch 1 wants to **sell** at 60 and buy back at 10 ($a=+1$, profit 50); branch 2 wants to **buy** at 80 to sell at 500 ($a=-1$, profit 420). At hour 1 the *higher* price wants the *lower* quantity, which no monotone curve can express, and hour 2 orders the pair the other way, so both hours force $a^{(1)}=a^{(2)}$. The objective collapses to $-185a$, optimal at $a=-1$: **185**, against **235** for unconstrained contingency. This is not a modeling wart, it is the constraint a real bidder faces, and it is why a bid curve stays strictly weaker than clairvoyance even at $\rho=0$. It is golden oracle 3 in [specs/bid-curves.md](specs/bid-curves.md).

### Feasibility on the scenario support (the stated limitation)

Each branch is feasible along its own path, but a realized price vector matching no scenario can accept quantities across hours that jointly violate the SoC balance: the auction clears each hour separately while the battery's energy constraint couples them. R2.6 enforces feasibility **on the support**, the standard treatment, and prices the residual nowhere. Imbalance settlement is what prices it in reality, which is R3.1.

### Scoring a curve on a realized path (evaluation semantics)

Measuring what a curve earned needs one more definition, because the object being scored is not a schedule. The auction resolves the curve hour by hour at the realized clearing price, so the **realized commitment** is

$$\boxed{ g^{DA,\star}_t = q_t\big(\pi^\star_t\big), \qquad q_t(\pi) = q_{t,j^\star}, \quad j^\star = \max\{j : p_{t,j} \le \pi\}, }$$

with $q_{t,0}$ extended below the lowest step. Assembled across hours from different branches, $g^{DA,\star}$ is **not** an R1.1 schedule: the terminal-SoC equality alone rules it out except by coincidence (measured: deliverable 0 times in 30, median terminal miss 1.38 MWh on a 2 MWh asset). That is the support-feasibility limitation above, made concrete.

So the commitment is scored as a **cash-flow obligation, not a schedule**. It enters the evaluation program only through the recourse budget, and the recourse dispatch carries the physics:

$$\boxed{ \max_{g}\ \sum_t \Delta t\ \pi^\star_t g_t \quad\text{s.t.}\quad g \text{ is R1.1-feasible},\quad \lvert g_t - g^{DA,\star}_t\rvert \le \rho\bar P. }$$

This is faithful to what a day-ahead auction obliges (deliver the accepted quantities; the battery still obeys physics) and it is the same settlement as above, under which the commitment acts only through the budget. Two consequences matter. First, it **agrees exactly with the §R2.5 scoring** wherever that one applies: for an R1.1-feasible commitment the two programs have the same feasible set and the same objective, so a scalar commitment is scored identically either way and the curve-versus-scalar comparison is fair. Second, the residual it leaves unpriced is the **delivery gap** $\sum_t \lvert g_t - g^{DA,\star}_t\rvert$, the volume the commitment promised and the battery did not deliver. Imbalance settlement is what charges for it (R3.1), so any study reporting bid-curve value reports the gap beside it rather than banking a number that assumes deviation is free.

**Considered but out of scope:** endogenous price / residual supply curve (price impact, the R3 work §R1.1 points at); block bids, exclusive groups, and linked bids; interpolating the curve between scenario prices (the submitted curve is a step function on the support); pricing the delivery gap (R3.1); multistage ($>2$-stage) trees.
