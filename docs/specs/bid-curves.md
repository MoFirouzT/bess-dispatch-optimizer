# Spec R2.6. Price-contingent day-ahead bid curves

**Status:** Implemented (gate green 2026-07-26; every build task and acceptance box ticked. Result: a null, reported below)
**Release:** R2  **Depends on:** R2.3 (the two-stage program this modifies), R2.2 (the scenario set the curve is measurable against), R2.5 (the per-window value harness the study reuses), R1.1 (the physics each commitment branch must satisfy)
**Phases:** R2.6 (2026-07-26)

## Objective

Replace R2.3's single day-ahead commitment with a **monotone hourly bid curve**: per hour, a nondecreasing map from clearing price to committed quantity, submitted before the price is known and resolved by the auction. Then measure whether that contingency converts into realized euros, and where on the recourse-budget axis it stops paying.

## The design driver: two things wear the name "bid curve"

`formulation.md` §R1.1 currently points bid curves at the R3 reflexivity work. That bundles two separable problems, and only one of them is about market power:

1. **Price impact (reflexivity).** Your own bid moves the clearing price, so price becomes endogenous and dispatch and price co-determine. Modeling it needs a residual supply curve. Genuinely R3, and genuinely out of scope for the 2 MWh study asset.
2. **Price contingency.** The clearing price is unknown at gate closure, so what you submit to a day-ahead auction is not a schedule but, per hour, a set of monotone (price, quantity) pairs; the auction then determines your dispatch. **A pure price-taker still needs this**, because it converts a blind commitment into a price-contingent one.

Problem 2 is uncertainty handling over a scenario set, which is Release 2's subject matter, not Release 3's. That is why this phase sits here. The correction to §R1.1 is part of the delta below.

Structurally the change is small: R2.3's first stage is one schedule shared across all scenarios (that sharing *is* the non-anticipativity condition). A bid curve relaxes the sharing in a controlled way. The commitment may depend on the realized price, but **only through that hour's price**, never through the rest of the path.

## Formulation reference

Implements [`formulation-uncertainty.md` §R2.6](../formulation-uncertainty.md#r26-price-contingent-day-ahead-bid-curves-optimizer-delta), which extends §[R2.3](../formulation-uncertainty.md#r23-risk-aware-two-stage-dispatch--intraday-recourse-optimizer-delta) and is summarized here in house notation (grid-side net export $g_t = p^{dis}_t - p^{ch}_t$, per-unit SoC config, $\pi / e / \eta / \Delta t$).

**First stage becomes scenario-indexed.** R2.3 has one commitment $g^{DA}$ with its own R1.1-feasible SoC trajectory. R2.6 carries one commitment branch per scenario, $g^{DA,(s)}$, each R1.1-feasible in its own right (whichever branch clears must be physically deliverable). Two constraint families make the family a bid curve rather than a clairvoyant schedule, imposed **per hour $t$**:

$$\boxed{ \pi^{(s)}_t \le \pi^{(s')}_t \implies g^{DA,(s)}_t \le g^{DA,(s')}_t, \qquad \pi^{(s)}_t = \pi^{(s')}_t \implies g^{DA,(s)}_t = g^{DA,(s')}_t. }$$

Monotonicity (sell more as the price rises) is also literally an exchange rule: EPEX requires submitted curves to be monotone. Sorting the scenarios by $\pi_t$ within each hour makes this $(S-1)T$ adjacent-pair constraints, not $S^2 T$.

**Why the two families are exactly the measurability condition (the lemma the phase rests on).** Together they say the map $\pi^{(s)}_t \mapsto g^{DA,(s)}_t$ is single-valued and nondecreasing, so there exists a nondecreasing $q_t(\cdot)$ with $g^{DA,(s)}_t = q_t(\pi^{(s)}_t)$ on the scenario support. That $q_t$ is the submitted curve. Without the tie family the program could read the rest of the path (two scenarios the auction prices identically at hour $t$ would receive different quantities), which is anticipativity wearing a bid curve's name. R2.3's shared schedule is the special case $q_t \equiv \text{const}$.

**Settlement.** The day-ahead leg settles at the price that cleared it, so with the auction reading of $\pi^{(s)}$ (decision 1) the per-scenario profit is

$$\boxed{ \text{profit}_s = \sum_t \Delta t \big[\pi^{(s)}_t g^{DA,(s)}_t + \pi^{(s)}_t (g^{(s)}_t - g^{DA,(s)}_t)\big] = \sum_t \Delta t\ \pi^{(s)}_t g^{(s)}_t. }$$

The recourse budget $|g^{(s)}_t - g^{DA,(s)}_t| \le \rho \bar P$ and the CVaR mean-risk objective carry over from §R2.3 unchanged, with $g^{DA}(t)$ read as $g^{DA}(s,t)$.

**The consequence that makes the phase testable.** At $\lambda = 0$ this expectation is *term-for-term identical* to R2.3's (§R2.3 already shows $g^{DA}$ cancels out of R2.3's expectation, leaving $\mathbb E_s[\sum_t \Delta t\ \pi^{(s)}_t g^{(s)}_t]$). So R2.6 and R2.3 maximize the same risk-neutral objective over feasible sets that nest, and the commitment does its work entirely through the budget, exactly as in R2.3. Two gates follow, and both are theorems rather than hopes:

- **Collapse identity.** Force all branches equal and the feasible set *is* R2.3's, so the objective matches exactly.
- **Provable bound.** The curve's feasible set strictly contains the scalar's, so at $\lambda = 0$ the R2.6 objective is $\ge$ the R2.3 objective on the same inputs.

At $\lambda > 0$ the two differ by design, not by accident: R2.3's fixed-price day-ahead leg is a forward hedge that compresses the per-scenario profit spread, and an auction leg is not. The identity is therefore gated at $\lambda = 0$ and the difference documented, not asserted away.

**Considered but out of scope (recorded in the delta):** endogenous price / residual supply curve (price impact, R3); block and exclusive-group bids (only per-hour curves here); linear-piecewise curve interpolation between scenario prices (the submitted curve is a step function on the support); multistage trees.

## Model size

The program goes from $1 + S$ R1.1 blocks to $2S$, so binaries roughly double: the existing benchmark ($S = 50$, 1224 binaries, about 2.05 s) becomes about 2400 binaries. Monotonicity adds $(S-1)T$ adjacent-pair inequalities, which are individually cheap.

**That estimate turned out to be badly wrong, and the measurement is in decision 4 below.** Counting binaries misses the structural cost: the monotonicity chain couples all $S$ commitment branches to one another within each hour, so the program loses the block-separability the R2.3 program has, and solve time grows steeply rather than by the roughly 2x the binary count suggests. The value study runs at $S = 10$ as a result.

## Parameters / configuration

| Item | Where | Default |
| --- | --- | --- |
| `bid_curve` (opt-in switch) | `solve_stochastic` keyword | `False`, so the default path stays R2.3 byte-identical |
| `rho` (recourse budget fraction) | as R2.3 | swept `{0, 0.1, 0.25, 0.5, 1.0}` for the value study |
| `lambda_`, `alpha` | as R2.3 | `0.0` / `0.95` |
| price tie tolerance | curve construction | market tick, `0.01` EUR/MWh (decision 3) |
| solver | reuse R1 | `appsi_highs`, tolerances unchanged |

## Interfaces

```python
# src/bess/stochastic/  (extends the existing two-stage module; imports optimizer/assets only)
def solve_stochastic(
    scenarios, battery, *, dt=1.0, alpha=0.95, lambda_=0.0, rho=0.5,
    solver="appsi_highs", fix_da=None, pi_da=None,
    bid_curve: bool = False,          # NEW: scenario-indexed first stage + curve constraints
    commitment=None,                  # NEW: score a decided obligation (evaluation semantics)
) -> "StochasticSchedule":
    """bid_curve=False reproduces R2.3 exactly. bid_curve=True indexes the commitment by
    scenario and imposes per-hour monotonicity and tie-equality in the clearing price.
    commitment scores an already-decided net-export obligation: it enters only the recourse
    budget, no day-ahead block is built, and the recourse dispatch carries the R1.1 physics.
    Mutually exclusive with fix_da, pi_da and bid_curve."""

def curve_response(curve, prices) -> list[float]:
    """The commitment a submitted curve incurs at a realised price path: per hour, the
    quantity of the last step whose price the realisation reaches, lowest step extended
    downward. Reading the curve at the prices it was built from returns that branch."""

# StochasticSchedule gains two optional fields, both None when bid_curve=False:
#   g_da_branches: list[list[float]] | None         # (S, T) the per-scenario commitment
#   curve: list[list[tuple[float, float]]] | None   # per hour, the (price, quantity) steps,
#                                                   # sorted by price, one step per tied price
# g_da keeps its meaning when bid_curve=False. Under a curve there is no single commitment,
# so it carries the probability-weighted mean of the branches: a reporting summary, and NOT a
# submittable object. The branches and the curve are the decision.

# src/bess/stochastic/  (study layer, alongside the R2.5/R2.5b harnesses)
def bid_curve_value_from_sets(...) -> "BidCurveValue"   # token-free core, realized-euro scoring
def bid_curve_value_across_windows(...) -> list         # per-window distribution, as R2.5b
```

## Build tasks

- [x] `formulation-uncertainty.md` §R2.6 (the delta above) plus a changelog entry, and the release split it required (decision 5). The §R1.1 correction separating price impact from price contingency landed with it.
- [x] Scenario-indexed first stage and the two curve constraint families in the two-stage builder, behind `bid_curve`.
- [x] Curve extraction: collapse the solved branches to per-hour `(price, quantity)` steps.
- [x] Golden and property gates below, token-free on hand-built scenario sets.
- [x] A rho-sweep value study (bid-curve value against a scalar commitment, per-window distribution) in the R2.5/R2.5b mould. No figure: the result is a null, and a null needs no chart (the R2.5b call).

> **Resolved 2026-07-26, approved and implemented.** R2.5b scores a commitment by pinning it into an evaluation solve with `fix_da`, which imposes the R1.1 physics on the commitment. A curve's *realized* commitment is assembled across branches, hour by hour, so it is not an R1.1 schedule (measured: 0 of 30 deliverable, above), and that scoring path is simply unavailable here. **Proposed resolution:** score the commitment as a **cash-flow obligation rather than a schedule**. Pass the realized commitment as a numeric vector that enters only the recourse budget $\lvert g_t - g^{DA}_t\rvert \le \rho\bar P$, with no day-ahead physics block, and let the recourse dispatch carry the R1.1 physics. This is faithful to what the auction actually obliges (deliver the accepted quantities; your battery still has to obey physics) and it is exactly the §R2.6 settlement, under which the commitment only ever acts through the budget. The unpriced residual is the delivery gap $\sum_t \lvert g_t - g^{DA}_t\rvert$, which the study should **report** as the imbalance exposure R3.1 would price. Scoring the scalar commitment the same way keeps the comparison fair, and costs nothing, since a scalar commitment is R1.1-feasible anyway. This is an evaluation-semantics change to §R2.6, so it was approved and written into the formulation before implementation, per the phase workflow.
- [x] Token-gated integration on real ENTSO-E NL, reporting the distribution; sign not asserted.
- [x] `ruff` / `format` / `mypy` / `lint-imports` (KEPT) / `lint_docs` clean; no R1, R2.2, R2.3, R2.5 gate touched.

## Result: a null

Measured on real NL 2024 (Mar-May, 33 scoreable windows, `S=10`, `history_days=28`, verified 2026-07-26):

| rho | BCV median | BCV mean | positive | quartiles | delivery gap, curve vs scalar |
|---|---|---|---|---|---|
| 0.25 | −0.00 EUR | −0.40 EUR | 30% | [−0.15, +0.00] | 4.00 vs 4.21 MWh |
| 1.00 | +0.00 EUR | +0.42 EUR | 12% | [+0.00, +0.00] | 7.91 vs 9.91 MWh |

**A price-contingent commitment does not convert into realized euros on this asset.** The designed instance shows the mechanism is real (+28.79 EUR at `rho=0`, decaying to exactly 0 at `rho=1`), so this is a statement about the market and the scenario set, not a broken implementation. It is the same mechanism that produced the R2.5 forecast-value null and the R2.5b tail null: the recourse adjusts after the price is known, so a commitment that anticipates the price better buys little. The `rho=0.25` mean is mildly *negative*, which is the honest out-of-sample cost of fitting the commitment more tightly to the training scenarios.

**The delivery gap is the more interesting number.** Median 4.00 MWh at `rho=0.25` and 7.91 MWh at `rho=1.00`, on a 2 MWh asset: the commitment promises volumes the battery then does not deliver, several times its own capacity over a day. This study does not price that, and imbalance settlement is what would (R3.1). Notably the curve's gap is *smaller* than the scalar's at both budgets, so the contingency does buy something real, just not euros under this settlement.

## Golden oracles

Exact and hand-computed, written before the code and locked at `1e-6`. All five share one designed asset: **2 MWh / 1 MW at $\eta = 1$, $e_0 = e^{\mathrm{tgt}} = 1$ MWh, $T = 2$**, so the terminal constraint reduces every feasible dispatch to $g = [a, -a]$ with $a \in [-1, 1]$, each branch's profit is linear in $a$, and the optimum sits at an endpoint. Scenarios are equiprobable.

| # | inputs | expected | why this case |
|---|--------|----------|---------------|
| 1 | $\pi = \{[10,90],[90,10]\}$, `fix_da = ([1,0],[0,1])`, `rho=0.5` (see note) | **objective 20.0 under both `bid_curve=True` and `False`** | the collapse identity, and with it the settlement algebra: same pinned commitment, same value |
| 2 | $\pi = \{[10,90],[90,10]\}$, `rho=0` | scalar **0.0**, curve **80.0**; branches $[-1,+1]$ and $[+1,-1]$; hour-1 curve `[(10,-1),(90,+1)]` | the escape. Mean prices are flat at 50, so every blind commitment settles at zero, while the curve buys cheap and sells dear in each state |
| 3 | $\pi = \{[60,10],[80,500]\}$, `rho=0` | curve **185.0**, equal to the scalar, and strictly below the clairvoyant **235.0** | monotonicity genuinely binds: the higher hour-1 price wants the lower quantity. A program returning 235 is not enforcing the auction rule |
| 4 | $\pi = \{[50,10],[50,500]\}$ and its mirror, `rho=0` | **205.0**, both branches equal at hour 1, one curve step | measurability: no peeking at the rest of the path through a price the auction prices identically. Unconstrained this is 245.0. The mirror is included so a one-sided rule cannot pass by luck of the sort order |
| 5 | $\pi = \{[10,90],[90,10]\}$, `rho=3` | both **80.0**, difference exactly 0 | the §R2.3 rho-limit collapse, restated: the commitment only ever mattered through the budget |

*Note on oracle 1:* the scenario set is $\{[10,90],[90,10]\}$; the pinned commitment $g^{DA} = [-1,+1]$ with `rho=0.5` leaves each branch $a \in [-1,-0.5]$, so branch $[10,90]$ earns $-80a \to 80$ and branch $[90,10]$ earns $+80a \to -40$, expectation 20. **The four scalar-side values (20, 0, 185, 205, 80) were verified against the existing R2.3 solver before the code was written**, so the arithmetic is checked, not asserted.

## Property tests

- **Opt-in identity:** `bid_curve=False` is byte-identical to R2.3 on every generated input (the R2.2b/R2.2c opt-in pattern).
- **Provable bound:** at `lambda_=0`, the R2.6 objective is `>=` the R2.3 objective on the same scenario set.
- **Monotone curve:** within every hour, quantity is nondecreasing in that hour's clearing price.
- **Tie equality:** equal prices within an hour give equal quantities.
- **Per-branch physical feasibility:** every commitment branch satisfies the full R1.1 physics (SoC balance and bounds, mutual exclusion, ramp, terminal) at its own path.
- **Budget:** `|g^(s) - g^DA,(s)| <= rho * P_bar` for every scenario and period.
- **Scale invariance and determinism:** as elsewhere in the repo.

Deliberately *not* a property: bid-curve value decreasing in `rho`. That is the expected shape, not a theorem, so it is reported by the study rather than gated (the R2.5 no-sign-assertion rule).

## Acceptance gate

*Blocks:* nothing downstream; R2.6 closes the Release-2 uncertainty arc. Every box must pass.

- [x] Golden oracles 1 to 5 pass at `1e-6`, including the collapse identity and the binding-monotonicity oracle.
- [x] All property invariants hold across seeded scenario draws.
- [x] The rho-sweep value study runs on real NL data and its per-window distribution is **reported with provenance, sign not asserted**. A null is a publishable result here, as in R2.5 and R2.5b. It is a null; see Result above.
- [x] Solve time reported next to the existing R2.3 number. Reported as a ladder rather than at `S = 50`, because `S = 50` does not finish: see decision 4.
- [x] `formulation.md` split lands with every cross-doc anchor still resolving (docs-lint checks this mechanically).
- [x] Lint / format / types / layers (KEPT) / docs-lint clean; no existing gate weakened, skipped, or loosened.

## Out of scope

- **Price impact / endogenous price:** the residual-supply-curve model, Release 3. The §R1.1 correction points there; this phase does not build it.
- **A price-impact sensitivity study** (re-score an existing schedule under $\pi_t^{\text{realized}} = \pi_t - \lambda g_t$, sweeping the impact coefficient and asset size, to measure the price-taker limitation rather than assert it). A cheaper standalone phase in the R2.5 re-scoring mould, and the named fallback if R2.6 is not taken. Not R3's endogenous-price optimization either way.
- **Off-support price vectors** (decision 2): a realized price path that matches no scenario accepts quantities across hours that jointly violate the SoC balance. Priced by imbalance settlement, which is R3.1. **Measured 2026-07-26, and it is the normal case rather than a corner:** over 30 trials (S=10, T=24, held-out realized paths), the curve's realized commitment was deliverable as an R1.1 schedule **0 times out of 30**, with a median terminal-SoC miss of **1.38 MWh on a 2 MWh asset** (max 3.43). The binding obstruction is the terminal-SoC *equality*: a commitment mixed across branches essentially never lands on it. This blocks the value study's scoring step and is the phase's open design question (see the note under Build tasks).
- **Block bids, exclusive groups, and linked bids;** the continuous intraday order book; multistage (more than two-stage) trees.

## Decisions (reviewed 2026-07-26)

Each was posed with a proposed answer and resolved as proposed; the lines below are the decision trail. Phase-local decisions only.

1. **What does $\pi^{(s)}$ mean, and where does the day-ahead leg settle?** The central one, and the reason the phase is not a pure addition. In the *data*, R2.2's scenarios are day-ahead clearing prices. In R2.3's *story* they play the realized intraday price, with a separate known $\pi^{DA}$ (default $\bar\pi$) settling the commitment. A bid curve conditions on the day-ahead **clearing** price, so under R2.3's story the curve would be conditioning on the intraday price, which is not known at gate closure: anticipativity, not contingency. **Resolved: the auction reading.** $\pi^{(s)}$ is the uncertain day-ahead clearing price; acceptance and settlement of the commitment both happen at $\pi^{(s)}_t$; the deviation settles there too, so R2.6 carries one price signal where R2.3 carries two. This follows the correction R2.5b already made for value measurement (settling the day-ahead leg at a forecast structurally penalizes what it scores). R2.3 keeps its own semantics untouched. The cost is stated in the delta, not hidden: the identity holds at $\lambda = 0$ only, because R2.3's fixed-price leg is a forward hedge and an auction leg is not. **Rejected:** clear on $\pi^{(s)}$ but settle at $\bar\pi$, which would pay a price different from the one that cleared you.
2. **Feasibility off the scenario support.** Each branch is R1.1-feasible along its own path, but the realized price vector need not match any scenario, and mixing accepted quantities across hours can violate the SoC balance. **Resolved: enforce feasibility on the support** (the scenario set is the model of the future, and this is the standard treatment in the day-ahead bidding literature), state the residual exposure plainly in the delta, and point it at R3.1 imbalance settlement, which is what prices it in reality.
3. **Tie tolerance.** Exact float equality would almost never fire, leaving near-ties to produce arbitrarily steep curve segments. **Resolved: round scenario prices to the market tick (0.01 EUR/MWh)** before sorting, and treat equality at that resolution as a tie. Domain-authentic, and it makes the tie family actually bind.
4. **Curve granularity.** **Resolved: one step per scenario** (no extra approximation), since R2.2's reduction already brings $S$ to about 50. A coarser price grid is a later optimization if solve time bites. **Reopened by measurement (2026-07-26): it bites, and the resolution above does not survive at production $S$.** Measured at $T=24$, $\rho=0.5$: scalar 0.08 / 0.13 / 0.37 / 0.93 s at $S = 5, 10, 20, 30$; the curve 0.08 / 0.50 / **23.3** / **326** s, and $S=50$ did not finish. The spec's cost estimate counted binaries and missed the structural cause: the monotonicity chain couples all $S$ commitment branches to one another within every hour, so the program loses the block-separability the R2.3 program has. **The proposed amendment was measured and rejected (2026-07-26).** Capping the curve at $K$ steps (bucket each hour's prices into $K$ rank-based groups, tie within a group) makes it **worse, not better**: $S=20$, $K=5$ took **122 s** against **23.3 s** un-capped. Tying branches adds equality constraints without removing variables, and it degrades the relaxation the branch-and-bound was using. Relaxing the MIP gap helps but not enough ($S=20$: 23.3 s to 12.2 s at `mip_rel_gap=1e-4`; $S=30$: 326 s to 74 s at `1e-3`), and it would trade away the exactness the golden oracles rest on. **Resolved instead: keep one step per scenario and run the value study at reduced $S$.** $S=10$ solves in 0.50 s, which makes a full per-window sweep cheap, against the house default of $S=30$ used by the R2.5/R2.5b studies. The reduction is a stated approximation of the phase, not a hidden one: it costs scenario-set fidelity (a larger Kantorovich distance to the unreduced set), and the study reports the $S$ it ran at. **Recorded as a limitation:** R2.6 does not scale to production scenario counts, and making it do so is a decomposition problem (the monotonicity chain is what couples the branches), not a tuning problem.
5. **The formulation split.** The file sat at 599 of its 600-line cap and R2.6 changes the optimizer, so unlike R2.2b/R2.2c it needed a canonical section rather than spec-only treatment. **Resolved: split by release, and done.** `formulation.md` keeps the preamble, conventions, model at a glance, R1.x, an index of the R2 sections, and the changelog for both files; `formulation-r2.md` holds R2.1 to R2.6. Every cross-doc anchor was repointed and docs-lint verifies them mechanically. **Rejected:** raising the cap in the charter, which would trade a structural fix for a threshold change.
6. **Phase id.** **Resolved: R2.6**, because this is a first-stage decision over the R2.2 scenario set with no new data layer, and it reads naturally after R2.5b. Consequence: the Tier 0 roadmap's R3.4 becomes the price-impact phase rather than the bid-curve phase, a rename to make in `planning/`.
7. **Governing reference.** **Resolved: name one**, since day-ahead bidding under price uncertainty is genuinely new theory here rather than textbook-ubiquitous technique. Candidates are Fleten and Kristoffersen on Nordic day-ahead bidding (the usual starting point) and Loehndorf and Wozabal for storage specifically. **Neither is verified yet.** Both were named from memory, so per CLAUDE.md §1 the edition and chapter or section must be checked against the publisher listing before either is cited, and house notation wins for shared quantities. Until that check happens the formulation section relies on nothing from them, and `references.md` §R2.6 stays unwritten.
