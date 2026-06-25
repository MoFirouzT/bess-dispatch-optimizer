# STATE — session continuity

Read this first (after `CLAUDE.md`), update it at the end of every working session.
Holds: current phase · what's done · what's next · known blockers.

---

## Current phase

**R1.2 — Piecewise-linear degradation cost.** Spec: [`docs/specs/R1.2-degradation.md`](specs/R1.2-degradation.md) — status **Draft (awaiting human review)**.

R1.1 is **committed** (deterministic core, gate green). R1.2 spec + formulation delta are drafted and **blocked on human review** before any tests/code (phase-gate workflow). The R1.2 formulation section in `formulation.md` is marked DRAFT.

## Done

- **Documentation foundation only.** No code yet — repo is docs + contract.
  - `CLAUDE.md` — operating contract (math discipline, doc tiers, phase workflow, layering, commands, guardrails).
  - `docs/formulation.md` — single source of truth; R1.1 deterministic core fully specified (grid-side metering; efficiency in SoC balance only).
  - `docs/conventions.md` — locked conventions (UTC, units, sign/metering, naming, config).
  - `docs/glossary.md`, `docs/market_reference.md` — domain knowledge banks.
  - `docs/decisions/README.md` — ADR process + index of 8 proposed ADRs (none written yet).
  - `docs/specs/R1.1-deterministic-core.md` — first work order.
  - `planning/MASTER_PLAN.md` — Tier 0, gitignored, strategy source of truth.
- **R1.1 doc-review pass (this session).** Human reviewed spec + formulation, found correct, gave comments — all resolved:
  - Bare `docs/formulation.md` mentions → section-anchored cross-reference links (spec, conventions, market_reference).
  - `BatterySpec` config locked to **Pydantic v2** (dropped "or dataclass" — startup validation has real value, matches conventions §5).
  - "1 MWh / 1 MW" glossed as energy/power rating = 1-hour (1C) asset, in formulation worked example + spec.
  - Oracle 3 `η` made explicit (`η^ch=η^dis=0.95`); oracle 3 check re-presented around the breakeven `1/η^rt ≈ 1.108` spread.
  - Removed the "discrepancy with master plan" note from the spec; corrected the stale "≈36.97" in the (Tier-0) master plan to **35.125**. Committed docs no longer reference the gitignored plan.
  - Added tolerance rationale (why `1e-6`, not zero) to the spec.
- **Scaffold + env (step 1, this session).**
  - Full `src/bess/` layer tree (13 packages with docstrings) + `tests/{golden,property,unit}/`.
  - `pyproject.toml`: src-layout (hatchling), deps `pyomo`/`highspy`/`pydantic>=2`, dev group `ruff`/`pytest`/`hypothesis`/`pytest-cov`/`import-linter`; ruff + pytest config; `[tool.importlinter] root_package = "bess"` (contract bodies TBD step 2).
  - `uv sync` green (Pyomo 6.10, HiGHS via highspy 1.14). Ruff check + format clean; `import bess` ok.
  - **Solver entry point resolved:** `appsi_highs` is available and solves a toy maximize correctly. Use `appsi_highs` as the spec assumes.
- **Layering + CI (step 2, this session).**
  - `[tool.importlinter]`: two `layers` contracts — core chain `api → explain → stochastic → recourse → optimizer → assets` (gives `optimizer ⊥ api` for free) + forecast feed `stochastic ← scenarios ← forecaster`. Unlisted modules (validation, backtest, data, viz) left unconstrained until their phases. `uv run lint-imports` → **2 contracts KEPT**.
  - `.github/workflows/ci.yml`: ruff check · ruff format --check · lint-imports · pytest, on `uv sync --frozen` (uv.lock committed-ready), Python pinned 3.13.
  - `tests/unit/test_solver_smoke.py`: HiGHS-available + toy-solve check (infra sanity, explicitly **not** a formulation gate). pytest green (1 passed).
- **Failing gate written (step 3, this session) — tests-first.**
  - `tests/golden/test_golden_oracles.py`: 3 oracles (40.0 / 35.125 / 0.0) checking objective + full schedule at tol 1e-6.
  - `tests/property/test_invariants.py`: Hypothesis. `test_core_invariants` (power caps, mutual exclusion, SoC bounds, exact continuity, terminal, objective consistency) @200 examples; `test_no_phantom_profit_when_prices_equal` @100; `test_ramp_respected_when_enabled` @100. Feasibility guaranteed via `soc_initial == soc_terminal` (idle always feasible).
  - Confirmed **red for the right reason**: `ModuleNotFoundError: bess.assets.battery` (API absent), not a test bug. Smoke test still green.
  - **Decided test-side API** (drives step 4): `BatterySpec` lives in `bess.assets.battery`; `solve(prices, spec, dt=...) -> Schedule` with `.p_charge/.p_discharge/.soc/.objective` (all length T, grid-side MW / MWh / €).
- **R1.1 implemented (step 4, this session) — gate green.**
  - `src/bess/assets/battery.py`: `BatterySpec` (Pydantic v2, frozen, cross-field SoC-window validation) + `Battery.register()` adding vars + constraints (1)(3)(4)(5); SoC bounds (2) via Var bounds. Single-asset attaches to model directly; multi-asset → Pyomo Block noted.
  - `src/bess/optimizer/core.py`: `build_model()` (asset registers physics; optimizer owns the maximize objective, no efficiency term), `solve()` (appsi_highs, optimality guard via `results.solver.termination_condition`), `Schedule` dataclass.
  - **Formulation finding (resolved, approved):** the "no phantom profit" invariant only holds for non-negative equal prices. Under uniformly negative prices the battery profits as a *paid load* (round-trip loss consumed at a negative price) — real, not phantom, and distinct from the simultaneous charge+discharge the binary forbids. Spec invariant corrected + objective-floor invariant added; **golden oracle 4** (`π=[-1,-1]` → 0.0975) added to lock it.
  - Two implementation bugs fixed during bring-up: optimality check reads `results.solver.termination_condition` (legacy-wrapped appsi returns classic `SolverResults`); `zip(strict=True)` for ruff B905.
- **SoC units inconsistency resolved → per-unit config (this session).** conventions §2 (locked) said SoC is per-unit in config, but the spec/`BatterySpec` used absolute MWh (invisible at the 1 MWh default). Resolved in favour of the convention: `soc_min`/`soc_initial`/`soc_terminal` are now per-unit fractions of `capacity` (∈ [soc_min, 1.0]); `Battery.register()` converts to MWh (`e_x = soc_x · capacity`); model + `Schedule.soc` stay MWh. Recorded in [ADR-0009](decisions/0009-soc-per-unit-in-config.md) (Accepted). Spec parameter table + tests updated; gate still green (8 passed). Now exercised at `capacity ≠ 1` via the property strategy.

- **Theory-reference methodology established (this session).** New rule in `CLAUDE.md` §1: each part picks **one governing reference** (textbook preferred), recorded in new `docs/references.md` (Tier-2) with why + rejected alternatives; **house conventions win for shared quantities** (reference governs only new concepts, reconciled to house notation); formulation sections stay brief summaries pinned to chapter/section, edition cited, verified before relying. Seeded `references.md` for R1.1 (Williams; domain Kirschen & Strbac) and R1.2 (Williams SOS2/PWL; domain Plett), with R2 candidates stubbed. Both formulation §R1.1 and §R1.2 now carry a governing-reference line; R1.2's inline reference list moved into `references.md`. *(Replaces the earlier ad-hoc references, incl. the unverifiable Xu et al. paper.)*

## Next (in order)

1. **Human reviews + approves** the R1.2 spec + formulation delta. Key decisions to hand-check: degradation is a *cost subtracted from revenue* (no efficiency term in the cash flow, not in SoC balance); throughput is **storage-side, both directions** `τ_t = η_ch·p_ch·dt + p_dis/η_dis·dt` (a round trip of depth q costs `2·g(q)`); convex PWL via λ-method + SOS2 (SOS2 slack under convexity, kept — parallels `u_t`); breakpoints per-unit of `τ_max` (ADR-0009 consistency); disabled ⇒ exactly R1.1. Golden oracles: **15.0** (bites), **44.0** (cheap→full), **12.5** (η<1, pins storage-side), **40.0** (disabled→R1.1). Rainflow + calendar aging are the genuinely-deferred items; equivalent-full-cycle is a cheap variation, not built.
2. On approval: flip spec → Approved, mark the formulation R1.2 section non-draft, write the **failing** R1.2 golden + property tests first, then implement to green. Do not break the R1.1 gate.

## Known blockers / open questions

- No blockers — implementation gate open.
- ~~Solver entry point~~ — resolved: `appsi_highs`.
- Confirm `dt` (Δt) stays a per-solve argument (hourly for R1.1 oracles; 15-min native deferred to R1.4 data layer). — spec says yes; carry forward.
- Default battery: 1 MW / 1 MWh (1-hour) to match the §5 sanity band; revisit if backtest targets a 2-hour asset.
- Minor: uv's managed interpreter is 3.12 locally; CI pins 3.13. Both satisfy `requires-python >=3.11`. Add a `.python-version` if exact-match reproducibility is wanted.

## Notes

- Golden oracle 2 objective is **35.125** — the canonical grid-side value. The spec derivation governs.
