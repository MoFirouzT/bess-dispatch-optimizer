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

## Planned (not yet adopted)

Chosen when the phase starts, then reconciled and recorded here. Candidates only — **not yet governing**:

- **R2.1 forecasting / conformal:** R. Hyndman & G. Athanasopoulos, *Forecasting: Principles and Practice* (free, OTexts); A. Angelopoulos & S. Bates, *A Gentle Introduction to Conformal Prediction…* (tutorial); Hastie, Tibshirani & Friedman, *Elements of Statistical Learning* (free) for gradient boosting.
- **R2.2–2.3 stochastic / scenarios / robust:** Birge & Louveaux, *Introduction to Stochastic Programming*; Shapiro, Dentcheva & Ruszczyński, *Lectures on Stochastic Programming* (free); King & Wallace, *Modeling with Stochastic Programming*; Ben-Tal, El Ghaoui & Nemirovski, *Robust Optimization*.
- **R2.3 recourse / MPC:** Rawlings, Mayne & Diehl, *Model Predictive Control: Theory, Computation, and Design* (free).
- **R2.4 decomposition (Benders):** Conejo, Castillo, Mínguez & García-Bertrand, *Decomposition Techniques in Mathematical Programming*.
