# Conventions

The stable rules of the codebase.
Intentionally restrictive so every module composes cleanly.
**Locked:** changing anything here requires an ADR (`docs/decisions/`).

*Assumes:
the symbols introduced in the [formulation](formulation.md) (`π / e / η / Δt`, grid-side power);
this file fixes their units, signs, and names across the code.*

---

## 1. Time

### Storage timezone

All timestamps stored in **UTC**. No exceptions.
Display timezone is `Europe/Brussels` (= `Europe/Amsterdam`, both CET/CEST), applied only at the presentation/reporting layer.
Module-to-module exchange is always UTC.

### Resolution

The **real BE/NL day-ahead market is 15-minute** (96 periods/day) since 2025-10-01.
The pipeline stores the native market resolution.

- `Δt` (period length in hours) is an **explicit parameter everywhere**: never hard-coded.
The model is resolution-agnostic and the loader emits whatever resolution the market published
([day-ahead is 15-minute native](decisions/day-ahead-15min-native.md)).
- The R1.1 golden oracles use hourly `Δt` so their optima stay hand-checkable.
- **The committed studies and examples run at `Δt = 1.0`**, because their evaluation windows close
before the 2025-10-01 switch, when the published series really was hourly.
That is a fact about the data, not a limit of the model:
`tests/property/test_backtest.py` gates a quarter-hourly series against its hourly equivalent
(same revenue, same MWh cycled, calendar-day windows of 96 periods), and the hypothesis cases
throughout `tests/property/` draw `Δt` from {0.25, 0.5, 1.0}.
- Each timestamp marks the **start** of its interval; values at `t` apply over `[t, t + Δt)`.

### DST and period counts

Storing in UTC sidesteps DST entirely (UTC has no DST).
A non-leap year has exactly:

- **35,040** periods at 15-min, **8,760** at hourly.

CET-anchored series would gain/lose 4 periods at the spring/autumn transitions; never anchor series to CET.
Date ranges are **closed-open** `[start, end)`.

### Index contract

Every time-indexed `pandas` object: tz-aware UTC index, explicit frequency (`15min` or `1h`), index name `timestamp`.

---

## 2. Units

| Quantity | Unit | Notes |
| --- | --- | --- |
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

Here the optimizer uses **two separate non-negative grid-side variables**, not one signed net power:

- `p_charge_mw` $= p^{ch}_t \ge 0$: power drawn from the grid.
- `p_discharge_mw` $= p^{dis}_t \ge 0$: power delivered to the grid.

**Metering is grid-side; efficiency lives only in the SoC balance, never in the objective** (the central correctness rule; see [formulation.md: "Conventions"](formulation.md#conventions)):

$$e_t = e_{t-1} + \eta^{ch} p^{ch}_t \Delta t - \frac{p^{dis}_t}{\eta^{dis}} \Delta t$$

Derived quantities:

- **Net power** `p_net_mw` $= p^{dis}_t - p^{ch}_t$ (used in the ramp constraint).
Sign: `+` = discharge/export, `−` = charge/import.
- **Cash flow:** `+` = revenue, `−` = cost.
Objective $= \sum_t \pi_t \Delta t (p^{dis}_t - p^{ch}_t)$: no efficiency term.

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

- All model parameters in a typed config (Pydantic v2) loaded from YAML;
validation errors surface at startup, never deep in a solve loop.
Never `yaml.safe_load` directly in business logic.
- Environment variables are for **secrets and paths only**, never model parameters (those belong in versioned config).
`.env` is gitignored; `.env.example` is committed and lists every variable read.

---

## 6. Logging & errors

- Structured logging (module-level loggers);
no f-string-built log messages that hide fields.
- The validation layer (R1.3) returns **structured, typed errors** (e.g. infeasibility reasons), never raw solver stack traces, across the API boundary.

---

## 7. Writing charter (documentation quality)

The rules that keep the docs clear and consistent.
The four marked **✓ lint** are enforced by `scripts/lint_docs.py` in CI; the rest are review judgment.
Math and theory discipline live in [`CLAUDE.md`](../CLAUDE.md) §1; doc-tier governance in §2.
This section is about the *writing*.
A line that must break a per-line check (for instance, to quote a banned word) can end with a `<!-- lint-ok -->` comment, used sparingly.

**Prose about code must be checkable, or not written.**
A sentence asserting a fact about the code is not executable, so nothing fails when the code moves underneath it and the claim rots invisibly.
`scripts/lint_docs.py` therefore also binds the checkable subset: a spec marked `Implemented` must have no unticked box and must carry its `Decisions` section; a `formulation*.md §R<n>.<m>` reference anywhere in the repo must name a section that file has; a spec's `bess.x.y` references must name real modules and attributes; `Depends on:` IDs must name real specs and form an acyclic graph; `file.md#anchor` links must resolve to a real heading; specs must carry no instruction that was already carried out ("to be recorded as ADRs", "when the module lands"); and math must render on GitHub.
The rule generalizes: **if a doc claim about code cannot be checked mechanically, either make it checkable or leave it out.**
Counts, module paths restated from memory, and prose duplicating a table are the usual offenders.

**Math renders through GitHub's Markdown first.**
GitHub treats a backslash before ASCII punctuation as a Markdown escape and drops the backslash *before* MathJax runs, so spacing control symbols (`\,`, `\;`, `\:`, `\!`) render as literal commas and semicolons inside formulas. <!-- lint-ok -->
Control *words* (`\quad`, `\Bigl`, `\sum`) are unaffected.
Spacing is cosmetic: delete it rather than reach for a workaround.
Inline math must not start or end with a space (`$ x$`), which can stop GitHub parsing the span as math at all. <!-- lint-ok -->

### Structure

1. **One source of truth; point, don't restate.**
    Equations live only in `formulation.md`; specs, README, and ADRs link to a section anchor.
    Decisions go in `docs/decisions/` (ADRs; *why*); spec/module docs describe *what*.
2. **Every `formulation.md` section follows the fixed skeleton:**
    governing-reference line → sets/parameters/variables tables → objective → constraints → *modeling notes* → **a worked numeric example tied to a golden oracle.**
    The worked example is mandatory; it is how a stuck reader self-debugs by recomputing.
3. **Justify, don't assert.**
    Each non-obvious step earns its *why*; theory claims are pinned to the governing reference's verified chapter, never cited from memory.
4. **Lead with the correctness trap.**
    State the failure mode before the mechanics (the grid-side-metering rule is the model).
5. **✓ lint: every doc opens with a purpose line and an `*Assumes:*` line.**
    Name what the doc takes as given (prerequisite docs, house conventions, defined terms) and link there, so a reader knows where to start.
    Point to prerequisites; do not gate on the reader's background. (Enforced on the README, `architecture.md`, and the canonical references.)
6. **No cold jargon.**
    Define or link any term/symbol at first use;
    `big-M`, `LP relaxation`, `epigraph`, `aFRR` get a `glossary.md` / `conventions.md` link the first time they appear.
7. **If it's spatial, draw it.**
    A flow, an envelope, a set of nested bounds → one small SVG (`docs/figures/`) beats a dense paragraph.
8. **✓ lint: no em dashes.**
    The em dash (`—`) is banned outright in committed docs, and the ban is enforced per line. <!-- lint-ok: defines the banned glyph -->
    Reach for a colon, semicolon, comma, period, or parentheses, and vary the device so the prose does not settle into one substitute.
    The glossary's term-definition format and the references' source-role format use a colon after the bold term; appositive asides take commas or parentheses; independent clauses take a semicolon or a full stop.
9. **✓ lint: one load-bearing claim per sentence; files stay under ~600 lines.**
    Push qualifiers into the *next* sentence rather than nesting three asides.
    Split a file that outgrows the cap (agents read whole files).
10. **No filler or tics.**
    Skip "it's worth noting" / "in essence", don't reach for a rule-of-three list every time, don't hedge.
    Plain words over flourish.
11. **✓ lint: no career or self-positioning language in committed files.**
    The specific banned words live in [`CLAUDE.md`](../CLAUDE.md) §2 (one source of truth); strategy stays in the gitignored `planning/` log.
12. **Reader confusion is data.**
    When someone trips on a passage, capture the fix as a glossary `*Gotcha:*` or an FAQ entry, not a one-off reply.
13. **Anti-patterns are explicit**:
    say what *not* to do; agents and readers both follow that well.
