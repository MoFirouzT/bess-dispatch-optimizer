# STATE — session continuity

Read this first (after `CLAUDE.md`), update it at the end of every working session.
Holds: current phase · what's done · what's next · known blockers.

---

## Current phase

**R1.4b — Productionized ENTSO-E day-ahead loader.** Spec: [`docs/specs/R1.4b-entsoe-loader.md`](specs/R1.4b-entsoe-loader.md) — status **Implemented (gate green)**; spec **Approved/frozen** (open questions resolved: entsoe-py, NL-2024-summer volatile slice, no committed data, `data/cache/` location).

R1.1–R1.4a done. R1.4b complete, tests-first: token-free golden parser + 4 unit tests on the fetch/cache/guard paths (fake client via monkeypatch) all green; **live integration test verified locally against real ENTSO-E** (token from `.env` + Keychain CA bundle) and skips cleanly without a token. Full suite **45 passed + 1 skipped (integration)**; ruff/format clean, **lint-imports 4 contracts KEPT** (`data` stays a leaf), docs linter clean. *(One pre-existing R1.2 property flake is failing independently — see Known blockers; deselected from the count above.)*

**Prior — R1.4a** (Implemented, gate green): engine + greedy/rolling/perfect-foresight baselines + gate-D sanity band on a deterministic synthetic series, leakage-safe.

**Data — no committed price data (copyright-clean).** Gate D runs on a **deterministic synthetic** in-memory series (`tests/golden/test_sanity_band.py`) ≈ €28k/MWh-yr, ordering + band hold. *History:* a real Energy-Charts CC BY 4.0 NL-2024 slice was used to validate the engine against real data (ceiling ≈ €27k/MWh-yr, rolling ≈ 99.7% of perfect foresight, greedy ≈ 56%), then **removed at the user's request** to keep the repo free of third-party data. Raw ENTSO-E is *not* committed either (its terms grant no public-redistribution right); ENTSO-E is the **runtime** source (R1.4b, fetched), and real-data band re-validation is an R1.4b token-gated **integration** test.

R1.4 was **split**: R1.4a (done) = engine + baselines + metrics + leakage + band; **R1.4b** = productionized `bess.data` ENTSO-E loader + multi-year + integration band re-validation.

**Key R1.2 decision (solver-driven):** HiGHS has **no SOS support** (`appsi_highs` raises `NotImplementedError` on SOS constraints). Since R1.2's degradation is *convex*, switched from λ-method+SOS2 to the **epigraph form** (`D_t ≥ a_k·τ_t + b_k` per segment) — exact for convex, pure LP, HiGHS-native, preserves all oracle values. SOS2 reframed as the non-convex tool (documented in formulation/glossary/references; needed only if a non-convex curve is added later, via a SOS-capable solver or binary encoding).

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
  - Removed the "discrepancy with master plan" note from the spec; corrected the stale "≈36.97" in the (Tier-0) master plan to **35.125**. Public docs no longer reference the gitignored plan.
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

- **Documentation-writing pass (this session).** Acted on a technical-writing review of the doc set — no math/semantics changed. Filled the empty Tier-1 **`README.md`** (what/why/status/reading-map) and created **`docs/architecture.md`** (module layering, doc tiers, reading order, stack) — both promised by `CLAUDE.md` §2 but absent. Purged career/positioning framing that had leaked into committed Tier-2 files (`glossary.md`, `market_reference.md`), per the §2 governing rule. Fixed a stale formulation anchor in the R1.2 spec (`#…-draft--awaiting-review` → clean). Corrected a now-stale "commit a real fixture slice" line in `market_reference.md` to match the locked no-committed-data decision. Formulation clarity edits: defined *epigraph*, *LP relaxation*, *big-M* at first use; broke up the two densest paragraphs (`τ_max`, negative-price `u_t`); added the cell-side reminder to the R1.3 Δ⁺/Δ⁻ asymmetry; added assumed-reader lines. Added **three SVG figures** (`docs/figures/`): grid-side metering, convex-PWL upper envelope, nested backtest bounds — referenced from `formulation.md`. Then thinned em-dash overuse: every sentence stacking 2+ em dashes was rephrased (0 remain in reader docs; structural `term — definition` / `Source — *role*` formats kept).

- **Writing charter + doc linter (this session).** Codified the writing rules in `docs/conventions.md` §7 (12 rules: structure, audience, prose mechanics, governance), with a pointer added to `CLAUDE.md` §2 and a `docs:` command in §6. Four rules are CI-enforced by new **`scripts/lint_docs.py`** (no stacked em dashes; `*Assumes:*` line on canonical docs; ~600-line cap; no career/positioning words), wired into `.github/workflows/ci.yml` as a "Docs (writing charter)" step. Linter has an inline `<!-- lint-ok -->` escape hatch. All gates green locally (ruff, format, lint-imports, lint_docs).

## Next (in order)

1. **Address the pre-existing R1.2 degradation property flake** (see Known blockers) — it is an R1.2 gate, independent of R1.4b, and should be resolved before R1.5. Needs a human/formulation call (don't loosen the EPS to silence it).
2. **R1.5** — live serving (FastAPI + circuit breaker + latency budget), per the R1.4b "out of scope" list. Draft `docs/specs/R1.5-*.md` from the master plan first; human review before implementation.

### R1.4b — implemented (this session)
- `entsoe-py` added; `bess.data.entsoe` exposes `fetch_day_ahead` (live BE/NL day-ahead → internal schema + parquet cache under gitignored `data/cache/`) and `parse_day_ahead_xml` (token-free A44 parse, reuses the same normalization). Shared schema check factored out of `fixtures.load_prices` → `fixtures.validate_price_series`, used by both loaders.
- Tests: golden parser on a **synthetic** A44 XML (1-based positions, A03 carry-forward gap, `PT60M`, UTC); unit tests for tz→UTC normalization, cache round-trip (no 2nd API call), lowercase-zone, unsupported-zone, missing-token. Live integration (`@pytest.mark.integration`, `tests/integration/`) token-gated + skipped without `ENTSOE_API_TOKEN`; registered the `integration` marker + a `bs4.XMLParsedAsHTMLWarning` filter in `pyproject`.
- `.env.example` added (token + Keychain CA-bundle steps); README gained a **Data** section.
- **Band finding (resolved, formulation-faithful):** the real NL **summer-2024** ceiling annualizes to ≈ **€51.9k/MWh-yr**, *above* the synthetic gate D's absolute €50k red flag — but that absolute is calm-calibrated. Formulation §5's band is **derived from the slice's own daily spread** (`c·spread`); on real hourly data the perfect-foresight ceiling is ≈ **1.25×** that 1-cycle/day mean-spread heuristic across *both* seasons (calm 25.95k vs heur 20.89k; volatile 51.9k vs heur 40.47k). The integration test asserts each ceiling sits in `[0.8, 1.6]×` its own heuristic + a 2× absolute backstop, and that the volatile band shifts up (wider spread, higher ceiling). No formulation change — this is the §5 band applied correctly to a volatile slice.

### R1.4b environment findings (verified this session — bake into impl)
- **Host correction:** ENTSO-E API is `https://web-api.tp.entsoe.eu/api` (**`tp`, not `tps`** — the old host is dead). `documentType=A44`, EIC `10YNL----------L` (NL) / `10YBE----------2` (BE), `periodStart/End` UTC `YYYYMMDDHHMM`, 400 req/min.
- **Schema:** `Publication_MarketDocument` → `TimeSeries` (one per day) → `Period` (resolution `PT60M`/`PT15M`) → `Point` (1-based `position`, `price.amount`), EUR/MWH, UTC. **A03 curve quirk:** missing `position` ⇒ carry the previous price forward (entsoe-py handles).
- **TLS/CA:** corporate MITM proxy → curl trusts it (Keychain) but uv-Python does **not**. Fix verified: export Keychain roots to `ca.pem`, set `REQUESTS_CA_BUNDLE`/`SSL_CERT_FILE`. Operator setup, not code. CI unaffected (no live API).
- **Feed sanity:** probed ENTSO-E NL prices matched published EPEX/ENTSO-E values (and the since-removed Energy-Charts slice) exactly ⇒ the parser targets the right series.
- **Licensing (binding):** commit **no** real price data — raw ENTSO-E grants no public-redistribution right; CC BY 4.0 third-party data was also removed per user preference. Committed test data is synthetic; ENTSO-E is fetched at runtime / in integration tests only.

### R1.4a key modeling decision (implemented)
- Three quantities over the *existing* optimizer: **ceiling** = full-horizon solve (overnight SoC free); **rolling** = per-day solves, each `e0=e_tgt=0` (deterministic agent has no next-day info at the gate ⇒ honest myopic model, intraday-optimal); **greedy** = 20/80 percentile rule (floor, can trade at a loss).
- Provable, gate-able ordering `0 ≤ V_greedy ≤ V_roll ≤ V*`; gap `V*−V_roll` = overnight arbitrage the deterministic agent can't capture → motivates R2. Headline metric `V_roll/V*`.
- No new math (formulation §R1.4 is derived-only). Leakage = decision for day `d` uses only `Π_d` + carried SoC. Sanity band derived from the fixture's own `mean_daily_spread`, not hard-coded.

### R1.3 design (implemented)
- Pre-flight is **pure** over `(prices, spec, dt)`; **accumulates all issues** (no fail-fast); does **not** re-validate the spec (Pydantic already did). `solve()` auto-runs `check()` as its first line (fail-closed).
- Catches: empty horizon, non-finite price (w/ index in `field`), non-positive/non-finite `dt`, and **terminal-SoC reachability** `−T·Δ⁻ ≤ Δ ≤ T·Δ⁺` (Δ⁺=η_ch·P̄_ch·dt, Δ⁻=P̄_dis·dt/η_dis), the only solve-time-only check (T from len(prices)).
- Ramp-free reachability is necessary-and-sufficient; with ramp it stays **necessary** (sound filter) — ramp-coupled infeasibility left to the solver guard. `solve()` now uses `load_solutions=False` so that residual class returns a termination condition instead of raising on solution load.
- The other §9 nightmares are explicitly *out of scope* for pre-flight (direction → golden/property gates; market rules → R1.4; degradation life → R1.2 monotonicity).

## R1.2 acceptance — recorded
- Oracles: **15.0** (bites), **44.0** (cheap→full cycle), **10.0** (η<1, pins storage-side), **40.0** (disabled→R1.1). All exact within 1e-6.
- Throughput is **storage-side, both directions** `τ_t = η_ch·p_ch·dt + p_dis/η_dis·dt`; `τ_max = min(power limit, SoC window e_max−e_min)`; breakpoints per-unit of `τ_max` (ADR-0009).
- Deferred: per-period cost in `Schedule` → R2.4; rainflow + calendar aging → hard; EFC + direction-specific wear → unneeded.

## Known blockers / open questions

- **R1.2 property flake (pre-existing, independent of R1.4b) — NEEDS A CALL.** `tests/property/test_degradation.py::test_degradation_never_pays` fails on a Hypothesis-found degenerate example (`prices=[0,0]`, top-segment `cost_eur≈3.3e-7`, `dt=0.25`): the with-degradation solve returns a phantom `+1.33e-6` objective vs `0.0` without, tripping `obj_with ≤ obj_without + EPS` (EPS=1e-6). Confirmed failing on clean `main` with R1.4b stashed → not caused by this phase. This is the same sub-tolerance class noted under "Notes" (degradation costs ~1e-7 sit below HiGHS's optimality/feasibility tolerance, so the reported objective carries ~1e-6 noise). **Do not loosen EPS to silence it** — needs a formulation/strategy call: e.g. floor the generated `cost_eur` magnitudes away from the solver tolerance, or relax the degenerate near-zero-cost inputs in the strategy (as was done earlier for the SoC anchor). Surfaced, not suppressed.
- ~~Solver entry point~~ — resolved: `appsi_highs`.
- Confirm `dt` (Δt) stays a per-solve argument (hourly for R1.1 oracles; 15-min native deferred to R1.4 data layer). — spec says yes; carry forward.
- Default battery: 1 MW / 1 MWh (1-hour) to match the §5 sanity band; revisit if backtest targets a 2-hour asset.
- Minor: uv's managed interpreter is 3.12 locally; CI pins 3.13. Both satisfy `requires-python >=3.11`. Add a `.python-version` if exact-match reproducibility is wanted.

## Notes

- Golden oracle 2 objective is **35.125** — the canonical grid-side value. The spec derivation governs.
- **R1.2 degradation property strategy hardened:** `problem_deg()` SoC anchor is now `{0.0} ∪ [1e-3, 1.0]` (was `[0, 1]`). A sub-tolerance target like `1e-6` sits below HiGHS's feasibility tolerance, so the solver could "satisfy" the terminal via a phantom micro-discharge whose degradation cost exceeded its revenue → spurious tiny-negative objective (tripped the `objective ≥ -EPS` floor). Not a formulation bug — degenerate input; invariant unchanged.
