# Formulation — single source of truth for the math

This file holds the canonical mathematics of the optimizer.
Specs, the README, and ADRs **point here**; they never restate equations.
Each phase appends a section; nothing is duplicated elsewhere.
Each section names its **governing reference** (see [references.md](references.md)) and summarizes only the theory the project implements; **house notation here and in [conventions.md](conventions.md) takes precedence** for shared quantities.

GitHub renders the `$$…$$` LaTeX below.

---

## Conventions

**Metering convention — the correctness trap.**
All power variables are measured at the **grid / AC terminal** (the metering point).
Efficiency therefore appears in the state-of-charge balance, and **never in the objective**:

- charging draws $p^{ch}_t$ from the grid, but only $\eta^{ch} p^{ch}_t$ reaches storage (charge losses);
- delivering $p^{dis}_t$ to the grid requires withdrawing $p^{dis}_t / \eta^{dis}$ from storage (discharge losses).

This is exactly the property-test invariant:

$$e_t = e_{t-1} + \eta^{ch}\, p^{ch}_t\, \Delta t \;-\; \frac{p^{dis}_t}{\eta^{dis}}\, \Delta t$$

The round-trip efficiency $\eta^{rt}=\eta^{ch}\eta^{dis}$ is **emergent**, not a separate term:
delivering 1 MWh to the grid ultimately costs $1/\eta^{rt}$ MWh drawn from the grid, enforced entirely by the balance above.
If an efficiency factor ever appears in the revenue expression, the formulation is wrong.

---

## R1.1 — Deterministic core

*Governing reference:* Williams, *Model Building in Mathematical Programming* — MILP formulation (binary indicators, mutual exclusion, big-M); domain context Kirschen & Strbac. House notation (preamble / `conventions.md`) governs shared quantities. See [references.md § R1.1](references.md#r11--deterministic-milp-dispatch).

### Sets

- $t \in \mathcal{T} = \{1,\dots,T\}$ — dispatch periods. $\Delta t$ = period length in hours (1.0 hourly, 0.25 quarter-hourly).

### Parameters

| Symbol | Meaning | Unit |
| --- | --- | --- |
| $\pi_t$ | day-ahead price in period $t$ (known) | €/MWh |
| $\Delta t$ | period length | h |
| $\eta^{ch}, \eta^{dis}$ | charge / discharge efficiency, $\in(0,1]$ | — |
| $\bar P^{ch}, \bar P^{dis}$ | max charge / discharge power | MW |
| $e_{\min}, e_{\max}$ | usable SoC bounds | MWh |
| $R$ | ramp limit on net power | MW per period |
| $e_0$ | initial SoC | MWh |
| $e^{\mathrm{tgt}}$ | terminal SoC target | MWh |

### Decision variables

| Symbol | Meaning | Domain |
| --- | --- | --- |
| $p^{ch}_t$ | grid-side charging power | $\ge 0$ |
| $p^{dis}_t$ | grid-side discharging power | $\ge 0$ |
| $e_t$ | state of charge at end of $t$ | $[e_{\min}, e_{\max}]$ |
| $u_t$ | charge indicator (1 = charging) | $\{0,1\}$ |

### Objective

Maximize day-ahead arbitrage revenue (grid-side cash flow, no efficiency term):

$$\max \;\; \sum_{t \in \mathcal{T}} \pi_t\, \Delta t \,\bigl(p^{dis}_t - p^{ch}_t\bigr)$$

### Constraints

**(1) State-of-charge balance** (with $e_0$ given as initial condition):

$$e_t = e_{t-1} + \eta^{ch} p^{ch}_t \Delta t - \frac{p^{dis}_t}{\eta^{dis}} \Delta t \qquad \forall t \in \mathcal{T}$$

**(2) SoC bounds:**

$$e_{\min} \le e_t \le e_{\max} \qquad \forall t \in \mathcal{T}$$

**(3) Power limits with mutual exclusion** (no simultaneous charge and discharge):

$$0 \le p^{ch}_t \le \bar P^{ch} u_t, \qquad 0 \le p^{dis}_t \le \bar P^{dis} (1 - u_t) \qquad \forall t \in \mathcal{T}$$

**(4) Ramp on net power** (for $t \ge 2$; $p^{net}_t \equiv p^{dis}_t - p^{ch}_t$):

$$-R \le p^{net}_t - p^{net}_{t-1} \le R \qquad \forall t \in \mathcal{T},\, t \ge 2$$

**(5) Terminal SoC:**

$$e_{T} = e^{\mathrm{tgt}}$$

### Modeling notes

- **Mutual-exclusion binary $u_t$.**
    With $\eta^{rt}<1$ and non-negative prices the LP relaxation already avoids simultaneous charge/discharge, so $u_t$ is usually slack — but it is *required* for correctness under negative prices (where burning energy via simultaneous charge+discharge could otherwise look profitable).
    Keep it.
    The big-M is the power cap itself ($\bar P^{ch}, \bar P^{dis}$), so no loose big-M is introduced.
- **Ramp.**
    Defined on net power for generality / grid-connection.
    Batteries ramp near-instantly, so $R$ is typically non-binding; disable by setting $R \ge \bar P^{ch} + \bar P^{dis}$.
    Note that a tight $R$ constrains the charge→discharge *transition* (a flip from $-\bar P^{ch}$ to $+\bar P^{dis}$ is a swing of $\bar P^{ch}+\bar P^{dis}$), so keep $R$ disabled for the R1.1 oracles unless a transition profile is being tested explicitly.
- **Sense.**
    Pyomo minimizes by default;
    set the objective sense to maximize (or minimize the negated expression).

### Worked example (sanity, $\eta = 1$)

$T=3$, $\pi=[10,50,20]$, $\Delta t=1$, a 1 MWh / 1 MW battery (energy capacity / power rating — a 1-hour, i.e. 1C, asset), $e_0=e^{\mathrm{tgt}}=0$, $R$ disabled → charge at $t_1$, discharge at $t_2$, idle at $t_3$; objective $=40$.
The full oracle set (including the lossy and no-trade cases) is the test contract in [specs/R1.1-deterministic-core.md](specs/R1.1-deterministic-core.md).

---

## R1.2 — Piecewise-linear degradation cost (DRAFT — awaiting review)

*Governing reference:* Williams, *Model Building in Mathematical Programming* — separable / piecewise-linear programming and SOS2 (the λ-method); domain context Plett, *Battery Management Systems*. House notation governs shared quantities. See [references.md § R1.2](references.md#r12--piecewise-linear-degradation-cost).

Extends R1.1 by appending a **degradation cost** to the objective.
All R1.1 sets, parameters, decision variables, and constraints (1)–(5) are unchanged — in particular the **SoC balance and grid-side metering are untouched**.
Degradation is a **cost subtracted from revenue**; it is *not* an efficiency factor and does *not* enter the SoC balance.
With no breakpoints configured the term is identically zero and the model reduces to R1.1 exactly.

### Rationale

Deep cycles age a cell faster than shallow ones, so the marginal cost of throughput **increases with depth** — a convex, increasing function.
A flat €/MWh fee cannot capture this; a convex piecewise-linear (PWL) cost can, and it makes marginal deep cycling unprofitable once the price spread no longer covers the rising degradation slope.

### Degradation measure

Per-period **storage-side throughput** — the energy that actually passes through the cell, counting **both directions** (charging into the cell and discharging out of it both age it):

$$\tau_t = \eta^{ch} p^{ch}_t\,\Delta t \;+\; \frac{p^{dis}_t}{\eta^{dis}}\,\Delta t \qquad \in [0,\ \tau_{\max}]$$

Charge and discharge are mutually exclusive in a period (R1.1 binary $u_t$), so exactly one term is non-zero; the per-period maximum is

$$\tau_{\max} = \max\!\Bigl(\eta^{ch}\bar P^{ch}\Delta t,\ \ \tfrac{\bar P^{dis}\Delta t}{\eta^{dis}}\Bigr).$$

This is a per-period throughput proxy for cycle depth.
**Out of scope** — genuinely harder or different, deliberately deferred:
**rainflow** cycle counting (path-dependent and non-convex — it does *not* reduce to a per-period cost) and **calendar aging**.
A coarser "equivalent-full-cycle" normalization is a cheap future variation, not a barrier; it is simply not built here.

### Parameters (new)

The degradation cost is a piecewise-linear (PWL) function of throughput, specified by **breakpoints** indexed $k=0,\dots,K$ (subscripts are indices, not exponents):

| Symbol | Meaning | Unit |
| --- | --- | --- |
| $\phi_k$ | $k$-th throughput breakpoint, **per-unit of $\tau_{\max}$**: $0=\phi_0<\phi_1<\dots<\phi_K=1$ (size- and $\Delta t$-independent, consistent with [ADR-0009](decisions/0009-soc-per-unit-in-config.md)) | p.u. |
| $x_k$ | the same breakpoint in absolute energy, $x_k=\phi_k\,\tau_{\max}$ | MWh |
| $g_k$ | degradation cost when throughput equals $x_k$: $0=g_0\le g_1\le\dots\le g_K$, and **convex** — the segment slopes $\dfrac{g_k-g_{k-1}}{x_k-x_{k-1}}$ are non-decreasing in $k$ | € |

The configured curve passes through $(x_0,g_0),\dots,(x_K,g_K)$, starting at the origin $(0,0)$ and bending upward (convex) as throughput deepens.

### Decision variables (new)

| Symbol | Meaning | Domain |
| --- | --- | --- |
| $\lambda_{t,k}$ | weight on breakpoint $k$ in period $t$ — the share of the convex combination placed on the point $(x_k,g_k)$ | $\ge 0$, SOS2 over $k$ (see (7)) |

### Constraints (new, $\forall t\in\mathcal T$)

The PWL cost is encoded by the **convex-combination ("λ") method**: write the throughput $\tau_t$ as a weighted average of the breakpoint abscissae $x_k$, and read the cost off as the *same* weighted average of the ordinates $g_k$.

**(6) Interpolation + partition of unity** (with $\tau_t = \eta^{ch} p^{ch}_t\Delta t + \tfrac{p^{dis}_t}{\eta^{dis}}\Delta t$, the throughput defined above):

$$\tau_t = \sum_{k=0}^{K}\lambda_{t,k}\,x_k, \qquad \sum_{k=0}^{K}\lambda_{t,k}=1, \qquad \lambda_{t,k}\ge 0$$

The first equation places $\tau_t$ as a convex combination of the breakpoints; the second forces the weights to sum to one (a genuine weighted average).

**(7) Adjacency — SOS2 on $\{\lambda_{t,k}\}_{k}$:** for each period $t$, the weight vector $\{\lambda_{t,0},\dots,\lambda_{t,K}\}$ is a **Special Ordered Set of type 2 (SOS2)** — *at most two weights may be non-zero, and if two are non-zero they must be adjacent* (consecutive indices $k$ and $k{+}1$).

*Why it is needed.* Without it the weights could land on non-adjacent breakpoints — e.g. $\tfrac12$ on $x_0$ and $\tfrac12$ on $x_2$ — which represents the straight **chord** from $(x_0,g_0)$ to $(x_2,g_2)$, not the function value at $\tau_t$. Restricting to two *adjacent* non-zero weights forces $\tau_t$ onto a single segment $[x_k,x_{k+1}]$, so the cost below returns the exact PWL value there. SOS2 is exactly the rule that turns the λ-weights into a faithful piecewise-linear interpolation (it generalizes SOS1, "at most one non-zero").

### Degradation cost

The period cost is the matching weighted average of the breakpoint costs:

$$D_t = \sum_{k=0}^{K}\lambda_{t,k}\,g_k \;\ge 0$$

### Modified objective

$$\max\ \sum_{t\in\mathcal T}\Bigl[\pi_t\,\Delta t\,(p^{dis}_t-p^{ch}_t)\ -\ D_t\Bigr]$$

Revenue is unchanged and still carries **no efficiency term**; the only addition is the subtracted $D_t\ge 0$.

### Modeling notes

- **Both directions, storage-side.** $\tau_t$ counts charge *and* discharge energy at the cell, so a full round trip of depth $q$ is penalized on both the charging period and the discharging period. Efficiency appears inside $\tau_t$ because it is a *cell-side energy* quantity — this is a degradation measure, not the objective's cash flow, which stays grid-side with no efficiency term.
- **SOS2 is slack under convexity (kept for correctness).** With the costs $g_k$ convex and $D_t$ minimized inside a maximization, the relaxation (dropping the SOS2 rule) already selects adjacent breakpoints on its own, so SOS2 is typically non-binding — exactly as the mutual-exclusion binary $u_t$ is usually slack in R1.1. It becomes *required* the moment the $g_k$ are non-convex; keep it. (For convex $g_k$ one could instead use an epigraph form $D_t\ge s_k\,\tau_t + b_k$ per segment and drop $\lambda$/SOS2 entirely; the $\lambda$-method is chosen to exercise SOS2 and to generalize to non-convex costs.)
- **Breakpoints vs. accuracy.** More breakpoints approximate a smooth degradation curve better at the cost of more $\lambda$ variables / SOS2 sets — the accuracy-vs-solve-time trade-off.
- **Monotonicity.** $g$ non-decreasing $\Rightarrow$ a deeper discharge never lowers degradation cost (the gate's monotonicity property).

### Worked example (degradation bites; $\eta=1$)

$T=2$, $\pi=[0,50]$, $\eta^{ch}=\eta^{dis}=1$, 1 MWh / 1 MW, $e_0=e^{\mathrm{tgt}}=0$, $\Delta t=1$, so $\tau_{\max}=1$. Breakpoints $\phi=[0,0.5,1]$, costs $g=[0,5,35]$ (slopes 10 then 60 €/MWh; convex). Terminal $=0$ forces discharge $=$ charge $=q$; with $\eta=1$ the throughput is $\tau=q$ in **each** of the two periods, so degradation is $2\,g(q)$ and the objective is $50q-2g(q)$: for $q\le0.5$ the margin is $50-2\cdot10>0$; for $q>0.5$ it is $50-2\cdot60<0$. Optimum at the kink $q^\star=0.5$ → charge $[0.5,0]$, discharge $[0,0.5]$, soc $[0.5,0]$, objective $=25-2\cdot5=\mathbf{15}$. The $\eta<1$ oracle (which pins the *storage-side* placement) and the full set are in [specs/R1.2-degradation.md](specs/R1.2-degradation.md).

---

## Changelog

- **R1.1** — deterministic core.
- **R1.2** — PWL degradation cost appended to the objective ($\lambda$-method + SOS2); R1.1 sets / variables / constraints and the SoC balance unchanged; reduces to R1.1 when no breakpoints are configured. *(Draft — under review.)*
