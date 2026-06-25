# References — the governing reference per part

How this project handles theory (the rule lives in `CLAUDE.md` §1):

- Each part picks **one governing reference** — educational, textbook preferred (lecture notes fine). It is the **notation and scope authority** for the *new* theory that part introduces.
- **House conventions take precedence for shared quantities.** Grid-side power, per-unit SoC, the symbols `π / e / η / Δt`, and unit-suffixed names are fixed by `docs/conventions.md` and the `docs/formulation.md` preamble. The governing reference rules only the genuinely new concepts a part adds; its notation is **reconciled to house style**, with any mapping noted.
- The `formulation.md` section is a **brief, self-contained summary** — only what the project implements, plus gate-critical nuance, plus an explicit out-of-scope list — pinned to the reference's chapter/section.
- **Secondary references** are allowed but strictly subordinate: pointers for context only, never competing notation.
- **Verify before relying.** Cite edition + chapter/section; do not quote results from memory. Editions below are recalled and **must be checked against the source** before being treated as authoritative.

This file grows one entry per part as phases are built (like `glossary.md`).

---

## R1.1 — Deterministic MILP dispatch

**Governing reference:** H. P. Williams, *Model Building in Mathematical Programming*, 5th ed., Wiley, 2013.
**Why:** the standard educational text for MILP *formulation* — binary indicator variables, mutual-exclusion modeling, and big-M (the chapters on integer/logical modeling). It governs how R1.1's discrete structure is written.
**Notation reconciliation:** house style wins. Williams' generic decision variables / objective map onto the project's `p^ch_t, p^dis_t` (grid-side), `e_t` (SoC, per-unit in config per [ADR-0009](decisions/0009-soc-per-unit-in-config.md)), `u_t` (binary), `π_t`, `Δt`. The mutual-exclusion binary and "big-M is the power cap" idiom are Williams'; the metering/efficiency placement is the house convention (`formulation.md` preamble), not from Williams.

**Secondary (domain context, pointer only):** D. S. Kirschen & G. Strbac, *Fundamentals of Power System Economics*, 2nd ed., Wiley, 2018 — day-ahead market mechanics, marginal pricing, and arbitrage; the economic backdrop for the objective. See also `docs/market_reference.md`.

**Alternatives considered:** D. Bertsimas & J. N. Tsitsiklis, *Introduction to Linear Optimization*, Athena Scientific, 1997 — excellent LP fundamentals but lighter on integer/logical modeling, so not the governing text; kept as a fundamentals backup.

---

## R1.2 — Piecewise-linear degradation cost

**Governing reference:** H. P. Williams, *Model Building in Mathematical Programming*, 5th ed., Wiley, 2013 — the chapters on **separable / piecewise-linear programming and special ordered sets (SOS1/SOS2)**. It governs the convex-combination (λ) method and the SOS2 adjacency rule.
**Notation reconciliation:** house style wins. The λ-method uses Williams' weights `λ_{t,k}` and breakpoints, written here with **subscript** indices `φ_k, x_k, g_k` (indices, not exponents); the throughput `τ_t` is built from the house grid-side power and efficiency.

**Secondary (domain context, pointer only):** G. L. Plett, *Battery Management Systems* (Vols. I–II), Artech House, 2015, with the companion open lecture notes "Algorithms for Battery Management Systems" (CU Boulder) — cell-aging fundamentals that justify a convex, depth-increasing degradation cost.

**Alternatives considered:** the battery cycle-aging-cost literature for electricity markets (rainflow-based marginal cycle costing). Deferred per the textbook-first policy: paper-specific and harder to verify; R1.2 takes only the textbook abstraction (a convex PWL cost), and rainflow is explicitly out of scope (`formulation.md` §R1.2).

---

## Planned (not yet adopted)

Chosen when the phase starts, then reconciled and recorded here. Candidates only — **not yet governing**:

- **R2.1 forecasting / conformal:** R. Hyndman & G. Athanasopoulos, *Forecasting: Principles and Practice* (free, OTexts); A. Angelopoulos & S. Bates, *A Gentle Introduction to Conformal Prediction…* (tutorial); Hastie, Tibshirani & Friedman, *Elements of Statistical Learning* (free) for gradient boosting.
- **R2.2–2.3 stochastic / scenarios / robust:** Birge & Louveaux, *Introduction to Stochastic Programming*; Shapiro, Dentcheva & Ruszczyński, *Lectures on Stochastic Programming* (free); King & Wallace, *Modeling with Stochastic Programming*; Ben-Tal, El Ghaoui & Nemirovski, *Robust Optimization*.
- **R2.3 recourse / MPC:** Rawlings, Mayne & Diehl, *Model Predictive Control: Theory, Computation, and Design* (free).
- **R2.4 decomposition (Benders):** Conejo, Castillo, Mínguez & García-Bertrand, *Decomposition Techniques in Mathematical Programming*.
