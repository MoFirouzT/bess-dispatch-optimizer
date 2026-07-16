# ADR-0023: The re-solve rule for MILP duals (fix-and-resolve with a relaxed idle tie-break)

**Status:** Accepted
**Date:** 2026-07-16

## Context

R2.4 reports the SoC-balance dual as a water value. The dispatch is a MILP (the mutual-exclusion binary $u_t$, R1.1 constraint (3)), which has no LP dual, so the standard escape is fix-and-resolve: fix the optimal commitment $u^\star$ and re-solve the resulting LP, whose duals are then defined. Fixing $u=u^\star$ restricts the feasible set to a subset that still contains the MILP optimum, so the LP optimum equals it exactly.

The trap is that $u^\star$ is **not unique**. At an idle period ($p^{ch}_t = p^{dis}_t = 0$) both $u_t=0$ and $u_t=1$ are optimal, the solver's tie-break is arbitrary, and constraint (3) gates each direction on $u_t$, so whichever value the solver returns clamps one direction's cap and moves the reported dual. This is not academic: on the reference instance ($T=3$, $\pi=[10,100,200]$, a 1 MW / 2 MWh battery idling through the 100 spike) three candidate re-solve rules each return the correct MILP objective 190 while reporting water values of **200, 100, and 10** EUR/MWh. Objective equality does not discriminate them. The true value is $\partial V^\star/\partial e_0 = 100$ (a marginal stored MWh clears at the middle period, since power is capped at the last).

A randomized property test cannot pick the rule: over 200 random instances all three matched the finite-difference truth, because random draws pin the water value through their trading periods, so the idle-rule ambiguity never binds. Only the constructed instance separates them.

## Decision

Report duals by fix-and-resolve with a **relaxed idle tie-break**, guarded by an objective-equality assertion:

- At idle periods with $\pi_t \ge 0$, relax both exclusion caps to the natural power caps $\bar P^{ch}, \bar P^{dis}$ (`free_idle`). This imposes both no-trade-band edges at once and is the only rule measured to recover $\partial V^\star/\partial e_0$.
- At idle periods with $\pi_t < 0$, keep $u^\star$ fixed (the relaxation is unsafe there, see below).
- On every solve, assert the re-solved LP objective equals the MILP's; if it does not, raise rather than report a dual the dispatch model does not support.

The $\pi_t \ge 0$ restriction is load-bearing. At $\eta^{rt} < 1$ a freed idle period at a negative price runs a SoC-neutral round trip that the market pays for, which R1.1's exclusion forbids, so the relaxed LP beats the MILP by exactly $\sum_{t:\text{ idle},\ \pi_t<0}\lvert\pi_t\rvert(1-\eta^{ch}\eta^{dis})\bar P\Delta t$ (measured: 2 violations in 600 unrestricted instances, +1.354275 and +12.9426, matching the formula to four decimals; 0 in 600 restricted). At $\eta^{rt}=1$ the relaxation is provably exact (the round trip is cash- and energy-neutral). Below 1 no counterexample survives the $\pi_t \ge 0$ restriction, and the equality assertion is the guard, not a proof.

A **no-trade band** is reported only where $\mu_t$ is tie-break invariant. Because $\mu$ is constant while SoC is interior, the tie-break moves a whole flat run's level, so invariance is a property of the run (measured constant, 110 of 110 runs). It is detected by solving the fallback tie-break both ways and comparing $\mu$ (one extra LP for the horizon, taken only when a negative-priced idle period exists). Where the two agree the band is reported and holds (35 of 35 measured); where they disagree it is suppressed (unpinned bands fail the action-consistency check 43 times in 46).

## Consequences

- **Easier:** the reported water value is the true marginal value of stored energy, not an artifact of the solver's branching, so a trader reading it can trust it. The band composes with the R1.2 wear and a transaction-cost read-off directly.
- **Harder:** the explain path solves the MILP once, re-solves the fixed LP, and (when a negative-priced idle period exists) re-solves the fallback tie-break once more. Three solves for the horizon, not one.
- **Enforced by:** golden oracle 1 (the 200/100/10 separation at an identical objective; $\mu=[100,100,100]$ matching $\partial V^\star/\partial e_0$), oracle 5 (the negative-price dump and its closed form), the soundness property (LP objective equals the MILP's on every draw), the band-consistency property (scoped to reported bands), and the pinned-iff-reported property. Weakening any lets the tie-break silently move the number again.

## Failure mode

A future refactor drops the objective-equality assertion "because fix-and-resolve is exact anyway," reintroducing the negative-price dump wherever the idle relaxation is applied unguarded. **Signal:** a reported water value at a lossy asset that exceeds the price ceiling, or a re-solved objective above the MILP's. **Mitigation:** the soundness property and oracle 5; both are red against the unguarded rule. A second failure mode is quietly widening band reporting to unpinned runs (to "cover more periods"), which reports bands the action contradicts; the pinned-iff-reported property guards it.

## Alternatives considered

- **Keep $u^\star$ as the solver returns it (`fix_u`), or fix idle power to zero (`fix_zero`).** Rejected: both return a valid-looking objective and a wrong water value (200 and 10 on the reference instance), being the two ends of the band the tie-break leaves open.
- **Intersect the two idle tie-breaks.** Sound, but it cannot be read off a solver, which returns a vertex of the dual optimal face, not the face: on the reference instance the two vertices are 200 and 10 and the truth (100) is neither. Recovering the faces needs the explicit dual and a max/min per period per tie-break, roughly $4T$ auxiliary LPs. And it is redundant where `free_idle` applies, since `free_idle` is the intersection computed in one LP (each tie-break imposes one side of the closed-form bound $\pi_t\eta^{dis}-c^{deg} \le \mu_t \le \pi_t/\eta^{ch}+c^{deg}$; `free_idle` imposes both). It survives only as the sound way to pin a value at a fallback period, which the per-run invariance test does more cheaply.
- **Report a value everywhere with a `pinned=False` flag and no suppression.** Rejected: at negative-priced idle periods the band contradicts the action most of the time, so a flagged-but-wrong band is worse than declining to report one.
