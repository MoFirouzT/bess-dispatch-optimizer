# References — the governing reference per part

How this project handles theory (the rule lives in `CLAUDE.md` §1):

- Each part picks **one governing reference** — educational, textbook preferred (lecture notes fine). It is the **notation and scope authority** for the *new* theory that part introduces.
- **House conventions take precedence for shared quantities.** Grid-side power, per-unit SoC, the symbols `π / e / η / Δt`, and unit-suffixed names are fixed by `docs/conventions.md` and the `docs/formulation.md` preamble. The governing reference rules only the genuinely new concepts a part adds; its notation is **reconciled to house style**, with any mapping noted.
- The `formulation.md` section is a **brief, self-contained summary** — only what the project implements, plus gate-critical nuance, plus an explicit out-of-scope list — pinned to the reference's chapter/section.
- **Secondary references** are allowed but strictly subordinate: pointers for context only, never competing notation.
- **Verify before relying.** Cite edition + chapter/section; do not quote from memory. Editions below are recalled and **must be checked against the source**; chapter pointers are descriptive until verified.

Each entry lists the source first, then — as sub-bullets — exactly what the project draws from it and where. This file grows one entry per part as phases are built (like `glossary.md`).

---

## R1.1 — Deterministic MILP dispatch

- **H. P. Williams, *Model Building in Mathematical Programming*, 5th ed., Wiley, 2013** — *governing reference* (MILP formulation).
  - Binary indicator variable + mutual-exclusion ("one of") modeling → constraint (3) and the `u_t` charge flag. *(Chapters on building integer-programming models / modeling logical conditions — verify exact ch.)*
  - "Let the natural bound be the big-M" idiom — here the power cap `P̄` *is* the big-M, so no loose constant is introduced → constraint (3). *(Same chapters.)*
  - Notation reconciliation: house style wins. Williams' generic decision variables / objective map onto `p^ch_t, p^dis_t` (grid-side), `e_t` (SoC, per-unit in config per [ADR-0009](decisions/0009-soc-per-unit-in-config.md)), `u_t`, `π_t`, `Δt`. The metering/efficiency placement is the house convention, not from Williams.
- **D. S. Kirschen & G. Strbac, *Fundamentals of Power System Economics*, 2nd ed., Wiley, 2018** — *secondary (domain context, pointer only).*
  - Day-ahead marginal pricing and storage arbitrage → the economic meaning of the objective. *(Chapter on electricity markets — verify.)* See also `docs/market_reference.md`.
- *Alternatives considered:* D. Bertsimas & J. N. Tsitsiklis, *Introduction to Linear Optimization*, Athena Scientific, 1997 — strong LP fundamentals but lighter on integer/logical modeling; kept as a fundamentals backup, not governing.

---

## R1.2 — Piecewise-linear degradation cost

- **H. P. Williams, *Model Building in Mathematical Programming*, 5th ed., Wiley, 2013** — *governing reference* (separable / piecewise-linear programming).
  - Convex PWL cost as the upper envelope of its segment lines → the **epigraph cuts** (6) and the cost `D_t`. *(Section on separable / piecewise-linear programming — verify exact ch.)*
  - SOS2 (special ordered set of type 2) — the method for **non-convex** PWL; documented but *not used* in R1.2 (it's convex) and unsupported by HiGHS. *(Section on special ordered sets — verify.)*
  - Notation reconciliation: house style wins. Breakpoints written with **subscript** indices `φ_k, x_k, g_k` (indices, not exponents); throughput `τ_t` and cost `D_t` built from house grid-side power + efficiency.
- **G. L. Plett, *Battery Management Systems* (Vols. I–II), Artech House, 2015** + companion open lecture notes "Algorithms for Battery Management Systems" (CU Boulder) — *secondary (domain context, pointer only).*
  - Cell aging fundamentals justifying a convex, depth-increasing degradation cost. *(Aging / life-modeling chapters — verify.)*
- *Alternatives considered:* the battery cycle-aging-cost literature for electricity markets (rainflow-based marginal cycle costing). Deferred per the textbook-first policy — paper-specific and harder to verify; R1.2 takes only the textbook abstraction (a convex PWL cost). Rainflow itself is out of scope (`formulation.md` §R1.2).

---

## R1.3 — Pre-flight validation

- **No new governing reference — engineering phase.** R1.3 introduces no new theory. The pre-flight feasibility test (per-period SoC-increment bounds → terminal reachability) is an **algebraic corollary** of the R1.1 model, so **Williams** (§R1.1, above) remains the governing authority; the derivation lives in [formulation.md § R1.3](formulation.md#r13--pre-flight-feasibility-derived-no-new-model).
  - Reachability of a box-bounded single-integrator under bounded input is elementary; no controllability / reachable-set text is invoked. Were a ramp-aware (coupled) reachable-set check ever built, a control reference (e.g. an MPC / reachable-sets text — see the R2.3 MPC candidate) would be adopted then and recorded here.
  - *Structured-error design* (typed `IssueCode` + accumulated `ValidationIssue`s) is a software-engineering choice, not a theory question — no reference needed.

---

## R1.4 — Backtest (walk-forward, baselines, sanity band)

- **M. López de Prado, *Advances in Financial Machine Learning*, Wiley, 2018** — *governing reference* (the new methodology: walk-forward evaluation + look-ahead/leakage discipline).
  - Walk-forward, never a random split on a time series; train/decide only on information available at decision time → the rolling backtest and the **leakage assertion** (gate C). *(Chapters on backtesting / cross-validation in finance — verify exact ch.)*
  - **Considered but out of scope:** purged $k$-fold CV and the embargo. These guard against *label* leakage when training a supervised estimator; R1.4 has no trained model (the optimizer is deterministic), so only the bare walk-forward + decision-time-information principle is used. Purging/embargo become relevant in R2.1 when a forecaster is fit. *(Verify.)*
  - Notation reconciliation: house style governs. The "information set at decision time" maps to the per-day price block $\Pi_d$ committed at gate closure (glossary: *gate closure*); no finance-specific notation is imported.
- **R. Sioshansi, P. Denholm, T. Jenkin et al., storage-arbitrage-value studies (e.g. *Energy Economics*, 2009)** — *secondary (domain context, pointer only).*
  - The perfect-foresight-ceiling vs. realistic-value framing for electricity storage → the ceiling/floor interpretation and the §5 plausibility band. *(Verify exact paper/year before relying.)*
- **D. S. Kirschen & G. Strbac, *Fundamentals of Power System Economics*, 2nd ed., Wiley, 2018** — *secondary (already governing-secondary for R1.1).* Day-ahead market mechanics behind the gate-closure information set.
- *Alternatives considered:* generic ML cross-validation texts (random k-fold) — **rejected**: a random split leaks the future on time-series data, the exact failure mode gate C guards against.

---

## R1.4b — ENTSO-E data loader

- **No new governing reference — engineering (data acquisition).** No new theory; R1.4's walk-forward/leakage methodology (López de Prado) still governs how the fetched data is used.
- **ENTSO-E Transparency Platform — RESTful API user guide** (`transparency.entsoe.eu`, *Static content → web API*) — *technical reference (not theory).* The authority for the request/response contract: host `web-api.tp.entsoe.eu/api`, `documentType=A44`, EIC domain codes, the `Publication_MarketDocument`/`TimeSeries`/`Period`/`Point` shape, and the A03 curve carry-forward. **Verified live** against an NL 2024 sample this session (R1.4b spec records the confirmed shape).
- **`EnergieID/entsoe-py`** — the Python client wrapping the above (EIC mapping, XML parsing, A03 expansion, 15/60-min). Implementation tool, pinned in the spec.

---

## Planned (not yet adopted)

Chosen when the phase starts, then reconciled and recorded here. Candidates only — **not yet governing**:

- **R2.1 forecasting / conformal:** R. Hyndman & G. Athanasopoulos, *Forecasting: Principles and Practice* (free, OTexts); A. Angelopoulos & S. Bates, *A Gentle Introduction to Conformal Prediction…* (tutorial); Hastie, Tibshirani & Friedman, *Elements of Statistical Learning* (free) for gradient boosting.
- **R2.2–2.3 stochastic / scenarios / robust:** Birge & Louveaux, *Introduction to Stochastic Programming*; Shapiro, Dentcheva & Ruszczyński, *Lectures on Stochastic Programming* (free); King & Wallace, *Modeling with Stochastic Programming*; Ben-Tal, El Ghaoui & Nemirovski, *Robust Optimization*.
- **R2.3 recourse / MPC:** Rawlings, Mayne & Diehl, *Model Predictive Control: Theory, Computation, and Design* (free).
- **R2.4 decomposition (Benders):** Conejo, Castillo, Mínguez & García-Bertrand, *Decomposition Techniques in Mathematical Programming*.
