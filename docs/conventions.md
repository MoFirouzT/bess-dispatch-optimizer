# Conventions

The stable rules of the codebase. Intentionally restrictive so every module composes cleanly. **Locked:** changing anything here requires an ADR (`docs/decisions/`).

---

## 1. Time

### Storage timezone
All timestamps stored in **UTC**. No exceptions. Display timezone is `Europe/Brussels` (= `Europe/Amsterdam`, both CET/CEST), applied only at the presentation/reporting layer. Module-to-module exchange is always UTC.

### Resolution
The **real BE/NL day-ahead market is 15-minute** (96 periods/day) since 2025-10-01. The pipeline stores the native market resolution.

- `Δt` (period length in hours) is an **explicit parameter everywhere** — never hard-coded.
- The R1.1 deterministic core may use hourly toy data (`Δt = 1.0`) as a deliberate first-pass simplification; the backtest (R1.4) and all downstream work use the native 15-minute series (`Δt = 0.25`).
- Each timestamp marks the **start** of its interval; values at `t` apply over `[t, t + Δt)`.

### DST and period counts
Storing in UTC sidesteps DST entirely (UTC has no DST). A non-leap year has exactly:
- **35,040** periods at 15-min, **8,760** at hourly.

CET-anchored series would gain/lose 4 periods at the spring/autumn transitions; never anchor series to CET. Date ranges are **closed-open** `[start, end)`.

### Index contract
Every time-indexed `pandas` object: tz-aware UTC index, explicit frequency (`15min` or `1h`), index name `timestamp`.

---

## 2. Units

| Quantity | Unit | Notes |
|---|---|---|
| Power | MW | grid-side (see §3) |
| Energy / capacity | MWh | never kWh in interfaces |
| Price (day-ahead, imbalance) | EUR/MWh | |
| Price (capacity: FCR/aFRR) | EUR/MW/h | reference only |
| Efficiency | per-unit (0–1) | never percent in interfaces |
| State of charge | MWh (absolute) in the model; per-unit only in config | |
| Money | EUR | full float internally; 2-decimal display |
| Durations | s (<1 min), min (<1 h), h otherwise | |

---

## 3. Sign & metering convention (reconciled with `formulation.md`)

**This supersedes the single-signed-power convention used in the earlier `bess-analytics` project.** Here the optimizer uses **two separate non-negative grid-side variables**, not one signed net power:

- `p_charge_mw` $= p^{ch}_t \ge 0$ — power drawn from the grid.
- `p_discharge_mw` $= p^{dis}_t \ge 0$ — power delivered to the grid.

**Metering is grid-side; efficiency lives only in the SoC balance, never in the objective** (the central correctness rule — see `docs/formulation.md`):

$$e_t = e_{t-1} + \eta^{ch} p^{ch}_t \Delta t - \frac{p^{dis}_t}{\eta^{dis}} \Delta t$$

Derived quantities:
- **Net power** `p_net_mw` $= p^{dis}_t - p^{ch}_t$ (used in the ramp constraint). Sign: `+` = discharge/export, `−` = charge/import.
- **Cash flow:** `+` = revenue, `−` = cost. Objective $= \sum_t \pi_t \Delta t (p^{dis}_t - p^{ch}_t)$ — no efficiency term.

If an efficiency factor ever appears in a revenue/objective expression, the code is wrong.

---

## 4. Naming

- **Physical-quantity variables and DataFrame columns are unit-suffixed, always:** `price_eur_mwh`, `p_charge_mw`, `p_discharge_mw`, `soc_mwh`, `eta_charge`, `duration_h`. Never bare `power`, `price`, `capacity`.
- Modules: short `lower_snake_case` (`optimizer`, not `optimizer_engine`).
- Classes: `PascalCase`; stateful-suffixes (`Runner`, `Builder`) only when truly stateful.
- Functions: verb-first `snake_case` (`build_model`, `solve`, `fetch_day_ahead`).
- Constants: `UPPER_SNAKE_CASE`.
- Time-series fixture files: `{stream}_{zone}_{YYYY}.parquet`, e.g. `da_be_2024.parquet`, `da_nl_2024.parquet`.

---

## 5. Configuration

- All model parameters in a typed config (Pydantic v2) loaded from YAML; validation errors surface at startup, never deep in a solve loop. Never `yaml.safe_load` directly in business logic.
- Environment variables are for **secrets and paths only**, never model parameters (those belong in versioned config). `.env` is gitignored; `.env.example` is committed and lists every variable read.

---

## 6. Logging & errors

- Structured logging (module-level loggers); no f-string-built log messages that hide fields.
- The validation layer (R1.3) returns **structured, typed errors** (e.g. infeasibility reasons), never raw solver stack traces, across the API boundary.

---

## 7. Documentation meta-rules (carried over, they work)

1. Files stay under ~600 lines; split if longer (agents read whole files).
2. Stable contracts (this file, `formulation.md`) are kept separate from phase/milestone content.
3. Decisions go in `docs/decisions/` (ADRs — *why*); module/spec docs describe *what*.
4. Cross-reference instead of repeating: one source of truth per fact.
5. Anti-patterns are explicit — say what *not* to do, agents follow that well.
