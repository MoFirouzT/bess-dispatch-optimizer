# References

*Source references for the parts of the project that use one.*

*Assumes: the [formulation](formulation.md) section each reference supports; this file records the source and scope per part, not the theory itself.*

How this project handles theory (see `CLAUDE.md` §1):

- Sourcing a part's *new* theory to a published reference is **at the human's discretion**, decided case by case; it is not a mandatory per-part procedure. Standard, textbook-ubiquitous techniques (e.g. big-M mutual exclusion) and pure engineering / data phases carry no reference.
- When a part **does** name a reference, that reference is the **notation and scope authority** for the genuinely new theory it introduces.
- **House conventions take precedence for shared quantities.** Grid-side power, per-unit SoC, the symbols `π / e / η / Δt`, and unit-suffixed names are fixed by `docs/conventions.md` and the `docs/formulation.md` preamble. A reference rules only the new concepts a part adds; its notation is **reconciled to house style**, with any mapping noted.
- The `formulation.md` section is a **brief, self-contained summary**: only what the project implements, plus gate-critical nuance, plus an explicit out-of-scope list, pinned to the reference's chapter/section.
- **Secondary references** are allowed but strictly subordinate: pointers for context only, never competing notation.
- **Verify before relying.** Cite edition + chapter/section; do not quote from memory. Editions below are recalled and **must be checked against the source**; chapter pointers are descriptive until verified.

Each entry lists the source first, then (as sub-bullets) exactly what the project draws from it and where.

---

## R1.1. Deterministic MILP dispatch

- **No governing reference.** Standard MILP modeling (mutual-exclusion binary, power-cap big-M); house notation governs.
- Domain context (pointer only): Kirschen & Strbac, *Fundamentals of Power System Economics* (also secondary for R1.4); `docs/market_reference.md`.

---

## R1.2. Degradation cost

- **B. Xu, A. Oudalov, A. Ulbig, G. Andersson, D. Kirschen, "Modeling of Li-Ion Battery Degradation for Cell Life Assessment," IEEE Trans. Smart Grid 9(2):1131–1140, 2018**: *governing reference* (cycle-based cell aging: degradation cost = replacement cost × sum of a DoD-stress function over rainflow-identified cycles).
- **Y. Shi, B. Xu, Y. Tan, B. Zhang, "A Convex Cycle-based Degradation Model for Battery Energy Storage Planning and Operation," 2017 (arXiv:1703.07968)**: *governing (convexity + the case we implement).* Proves `Σ Φ(d_i)` is convex in the SoC profile (Thm 1); §II-C-1 states the linear DoD stress `Φ(d)=k₁d` is equivalent to the linear power-based cost. *(Verify Thm 1, §II-C-1.)*
- **B. Xu, Y. Shi, D. Kirschen, B. Zhang, "Optimal Regulation Response of Batteries Under Cycle Aging Mechanisms," 2017 (arXiv:1703.07824)**: cycle depths from control actions (Eq. 6, the efficiency-weighted SoC increment) and the half-cycle-counts-half convention (§III-B). *(Verify Eq. 6, §III-B.)*
  - **What we adopt:** the **linear DoD-stress case**, which reduces to a linear marginal wear cost `c^deg` (€/MWh) on storage-side throughput `τ_t`; `c^deg` set from cell replacement cost ÷ lifetime throughput (standard arbitrage practice, ≈ €7–15/MWh). Notation reconciled to house style (grid-side power, per-unit efficiency).
- **H. P. Williams, *Model Building in Mathematical Programming*, 5th ed., Wiley, 2013**: *secondary (technique, deferred use).* Convex-PWL **epigraph** linearization; the technique that would embed a piecewise-linear `Φ` in the nonlinear-stress MILP (future work), unused in the linear case. *(Separable / piecewise-linear programming; verify ch.)*
- **G. L. Plett, *Battery Management Systems* (Vols. I–II), Artech House, 2015**: *secondary (domain context, pointer only).* Cell aging fundamentals (DoD-dependent life). *(Aging / life-modeling chapters; verify.)*
- *Alternatives considered:* the **nonlinear convex** cycle-aging model (exponential/polynomial `Φ`; Xu 2018, Shi 2017) captures the deep-cycle penalty but requires rainflow (no closed form) → convex-but-not-LP (Shi's subgradient) or a cycle-detection MILP. Deferred to keep the LP/MILP core (`formulation.md` §R1.2, referenced future work). The earlier self-derived convex-PWL-of-throughput proxy was dropped: it matched no source.

---

## R1.3. Pre-flight validation

- **No governing reference; engineering phase.** No new theory: the pre-flight feasibility test is an **algebraic corollary** of the R1.1 model, derived in [formulation.md: R1.3](formulation.md#r13-pre-flight-feasibility-derived-no-new-model).

---

## R1.4. Backtest (walk-forward, baselines, sanity band)

- **No governing reference.** Walk-forward evaluation and the decision-time (no-look-ahead) information set are standard time-series backtesting practice: train/decide only on information available at gate closure, never a random split on a time series → the rolling backtest and the **leakage assertion** (gate C). The principle predates any single source (walk-forward analysis, look-ahead-bias avoidance) and needs no cited authority.
  - *Deferred to R2.1:* purged $k$-fold CV and the embargo, the leakage-control machinery specific to a *fitted* estimator (López de Prado, *Advances in Financial Machine Learning*, Wiley, 2018). R1.4 has no trained model (the optimizer is deterministic), so only the bare walk-forward + decision-time principle applies; purging/embargo attach to the R2.1 forecaster.
  - Notation reconciliation: house style governs. The "information set at decision time" maps to the per-day price block $\Pi_d$ committed at gate closure (glossary: *gate closure*); no finance-specific notation is imported.
- **R. Sioshansi, P. Denholm, T. Jenkin et al., storage-arbitrage-value studies (e.g. *Energy Economics*, 2009)**: *secondary (domain context, pointer only).*
  - The perfect-foresight-ceiling vs. realistic-value framing for electricity storage → the ceiling/floor interpretation and the [sanity band](formulation.md#sanity-band-gate-d). *(Verify exact paper/year before relying.)*
- **D. S. Kirschen & G. Strbac, *Fundamentals of Power System Economics*, 2nd ed., Wiley, 2018**: *secondary (already governing-secondary for R1.1).* Day-ahead market mechanics behind the gate-closure information set.
- *Alternatives considered:* generic ML cross-validation texts (random k-fold); **rejected**: a random split leaks the future on time-series data, the exact failure mode gate C guards against.

---

## R1.4b. ENTSO-E data loader

- **No new governing reference; engineering (data acquisition).** No new theory; R1.4's walk-forward/leakage discipline (standard time-series practice) still governs how the fetched data is used.
- **ENTSO-E Transparency Platform RESTful API user guide** (`transparency.entsoe.eu`, *Static content → web API*); *technical reference (not theory).* The authority for the request/response contract: host `web-api.tp.entsoe.eu/api`, `documentType=A44`, EIC domain codes, the `Publication_MarketDocument`/`TimeSeries`/`Period`/`Point` shape, and the A03 curve carry-forward. **Verified live** against an NL 2024 sample this session (R1.4b spec records the confirmed shape).
- **`EnergieID/entsoe-py`**: the Python client wrapping the above (EIC mapping, XML parsing, A03 expansion, 15/60-min). Implementation tool, pinned in the spec.

---

## R2.1. Probabilistic forecaster (conformal intervals)

*Selected at R2.1 draft ([spec](specs/R2.1-forecaster.md)); reconciled/verified before implementation.*

- **A. Angelopoulos & S. Bates, *A Gentle Introduction to Conformal Prediction and Distribution-Free Uncertainty Quantification*** (tutorial); *governing reference* (the new theory: conformal prediction).
  - Split/inductive conformal and **distribution-free marginal coverage** under exchangeability → the coverage gate (empirical ≈ nominal under walk-forward). *(Verify the sections on split conformal + CQR.)*
  - Conformalized quantile regression (CQR) → hour-adaptive interval width over LightGBM quantile models. *(Verify.)*
  - Notation reconciliation: house style wins. Target/price stays `π_t` (€/MWh, grid-side) on the UTC series; conformal `α` maps to `confidence_level = 1 − α`.
- **R. Hyndman & G. Athanasopoulos, *Forecasting: Principles and Practice*** (OTexts, free); *secondary (methodology, pointer only).* Calendar/lag feature construction and honest time-series evaluation. *(Verify chapter.)*
- **Hastie, Tibshirani & Friedman, *Elements of Statistical Learning*** (free); *secondary (the base learner, pointer only).* Gradient-boosted trees. *(Verify chapter.)*
- **M. López de Prado, *Advances in Financial Machine Learning*, Wiley, 2018**: *governing reference for the evaluation discipline* at R2.1. The walk-forward / decision-time principle is standard (used already in R1.4 without a citation); what makes López governing *here* is the leakage-control machinery a fitted model needs: **purged $k$-fold CV and the embargo**, flagged in the R1.4 entry as becoming live once a forecaster is trained. *(Verify the CV/embargo sections.)*
- *Alternatives considered:* bare quantile regression (no finite-sample coverage guarantee), kept as the CQR base learner rather than the deliverable; bootstrap/Gaussian residual intervals; distribution-assuming, rejected for distribution-free conformal.
- **MAPIE** (`scikit-learn-contrib/MAPIE`, 1.x); implementation tool for the conformal wrappers (`SplitConformalRegressor`, `ConformalizedQuantileRegressor`); pin the major version (API changed at 1.0).

---

## R2.1b. Forecast-drift monitor

- **No new governing reference; engineering / monitoring phase.** R2.1b introduces no new modelling theory; the R2.1 conformal reference (Angelopoulos & Bates) still governs the forecaster and López de Prado governs its evaluation discipline (walk-forward with purging/embargo).
- **Population Stability Index (PSI)**: a standard population-stability metric from applied credit-scoring / model-monitoring practice (binned distribution divergence; the ≥0.2 "significant shift" convention). Cited as a standard statistic, not a governing textbook. The regime-shift-vs-staleness *framing* (staleness = worse-than-a-seasonal-naive baseline) is the project's design, recorded in [ADR-0015](decisions/0015-drift-staleness-before-regime.md).

---

## R2.1c. Exogenous day-ahead fundamentals features

- **No governing reference; feature-engineering phase.** R2.1c adds exogenous predictors to the R2.1 forecaster and introduces no new modelling theory; Angelopoulos & Bates still governs the conformal wrapper and López de Prado the evaluation discipline.
- **Residual load / merit order (domain context, not relied on):** the day-ahead price as the intersection of a step supply stack and demand, with *residual load* (load minus must-run wind/solar) as the position on the stack. Textbook-ubiquitous power-market context; used as motivation, not a cited method. The leakage-safe **contemporaneous alignment** of day-ahead forecast features is the project's own rule, recorded in [ADR-0024](decisions/0024-day-ahead-forecast-feature-alignment.md).

---

## R2.2. Scenario generation + reduction

*Selected at R2.2 draft ([spec](specs/R2.2-scenarios.md)); reconciled/verified before implementation.*

- **J. Dupačová, N. Gröwe-Kuska & W. Römisch, *Scenario reduction in stochastic programming: an approach using probability metrics* (Math. Programming, Ser. A, 2003)**, with **H. Heitsch & W. Römisch, *Scenario reduction algorithms in stochastic programming* (Comput. Optim. Appl. 24, 2003)**: *governing reference* (the new theory: probability-metric scenario reduction).
  - The Kantorovich (Wasserstein) distance between discrete distributions, its **closed form under optimal redistribution** (deleted mass to the nearest kept atom), and **fast forward selection** / backward reduction → the reduction distance and greedy algorithm in [formulation.md: R2.2](formulation.md#r22-scenario-generation--reduction-uncertainty-representation-no-optimizer-change). *(Verify the theorem/section numbering and year before relying.)*
  - **Deviation from the textbook-first policy, stated explicitly** (as R2.1 does for the López de Prado evaluation discipline): the reduction method is paper-defined and has no textbook of equal precision; these two 2003 papers are *the* source, so they are named governing rather than a textbook. Reconciled to house style: a scenario is a price path $\pi^{(s)}$ (€/MWh, grid-side, UTC schema), probabilities $p_s$; the probability metric is written $D_\ell$.
- **A. King & S. Wallace, *Modeling with Stochastic Programming*, Springer, 2012**: *secondary (scenario-generation framing, pointer only).* What a good scenario set must preserve and why reduction is stability-driven, not cosmetic. *(Verify chapter.)*
- **Birge & Louveaux, *Introduction to Stochastic Programming*; Shapiro, Dentcheva & Ruszczyński, *Lectures on Stochastic Programming* (free):** *secondary (foundations, pointer only);* scope authority moves here for R2.3, not R2.2.
- *Alternatives considered:* **moment matching** (match a chosen moment list by construction) couples scenario quality to that list and carries no distance-stability bound; kept as noted-not-built. **k-means** clustering of paths is retained as the pragmatic *baseline* the gate compares against ([ADR-0018](decisions/0018-forward-selection-over-kmeans.md)), not the governed method. **ARIMA/GARCH** parametric generation on raw prices is a deferred second generator path.

---

## R2.3. Risk-aware two-stage dispatch + intraday recourse

*Selected at R2.3 draft ([spec](specs/R2.3-stochastic-recourse.md)); reconciled/verified before implementation. R2.3 introduces more than one new theory, so it names one governing spine with two subordinate-but-authoritative sub-concept references (open question 3, resolved: one phase, not an R2.3a/b split).*

- **J. R. Birge & F. Louveaux, *Introduction to Stochastic Programming*, 2nd ed., Springer, 2011**: *governing reference* (the spine: two-stage recourse and the value metrics).
  - First-stage / second-stage (recourse) split and **non-anticipativity** → the shared day-ahead commitment `g^DA` vs. per-scenario recourse `g^(s)`. *(Two-stage recourse chapters; verify.)*
  - **VSS** (value of the stochastic solution) and **EVPI**, and the ordering EEV ≤ RP ≤ WS → the R2.3 metric harness, extending R1.4's `V^greedy ≤ V^roll ≤ V*`. *(Chapter on the value of information / the stochastic solution; verify.)*
  - Notation reconciliation: house style wins. Scenarios `π^(s)`, probabilities `p_s` (R2.2 schema); the generic first/second-stage vectors map onto `g^DA` and the per-scenario R1.1 dispatch.
- **A. Shapiro, D. Dentcheva & A. Ruszczyński, *Lectures on Stochastic Programming: Modeling and Theory*, 2nd ed., SIAM, 2014** (free): *subordinate-authoritative (CVaR / coherent risk).*
  - **CVaR** as a coherent risk measure and the **Rockafellar-Uryasev** linearization (`CVaR_α = min_η η + (1/(1−α))·E[(L−η)^+]`) → the mean-risk objective, VaR auxiliary `η`, tail slacks `z_s`. Method origin: R. T. Rockafellar & S. Uryasev, *Optimization of Conditional Value-at-Risk* (J. Risk, 2000). *(Coherent-risk-measure chapter; verify.)*
- **J. B. Rawlings, D. Q. Mayne & M. Diehl, *Model Predictive Control: Theory, Computation, and Design*, 2nd ed., Nob Hill, 2017** (free): *subordinate-authoritative (receding-horizon MPC).*
  - Receding-horizon control, state continuity across windows, and warm-start → the intraday recourse realization ([ADR-0021](decisions/0021-mpc-recourse-out-of-sample-vss.md)); plant model = SoC balance, disturbance = the price forecast. *(Receding-horizon / feasibility chapters; verify.)*
- **Bertsimas & Sim, *The Price of Robustness* (Oper. Res., 2004); Ben-Tal, El Ghaoui & Nemirovski, *Robust Optimization* (Princeton, 2009):** *secondary (the robust alternative, pointer only).* The Γ-budget robust counterpart to CVaR, documented not built ([ADR-0020](decisions/0020-cvar-mean-risk-over-robust.md)).
- *Alternatives considered:* **hard chance constraints** (per-scenario indicator binaries + big-M; the soft CVaR objective stands in); **mean-variance** (variance penalizes upside symmetrically; CVaR is the right tail measure); **full 24-hour here-and-now commitment** (the VSS = 0 trap, kept as a golden oracle only, [ADR-0019](decisions/0019-day-ahead-intraday-two-stage.md)).

---

## R2.4. Shadow-price explainability

- **No governing reference.** LP duality, shadow prices, and fix-and-resolve for MILP duals are standard optimization technique (the same category as R1.1's big-M mutual exclusion). The substantive content, the water value, the no-trade band, the interior-SoC flatness, is an **algebraic corollary** of the R1.1/R1.2 stationarity conditions, derived in [formulation.md: R2.4](formulation.md#r24-shadow-price-explainability-derived-no-optimizer-change), not imported.
- **Terminology origin (context, not a source relied on):** "water value" is borrowed from **hydro-thermal / reservoir scheduling**, where the shadow price of the storage balance is the marginal value of water held behind a dam. The metaphor is exact (stored energy in place of stored water), and the term is used here for that lineage, not to ground any claim; verify edition + section before citing a specific hydro-scheduling text.

---

## Planned (not yet adopted)

Chosen when the phase starts, then reconciled and recorded here. Candidates only; **not yet governing**:

- **R2.4 decomposition (Benders), out of scope in the R2.4 spec:** Conejo, Castillo, Mínguez & García-Bertrand, *Decomposition Techniques in Mathematical Programming*. Only relevant if the optional Benders / Julia comparison is ever built.
