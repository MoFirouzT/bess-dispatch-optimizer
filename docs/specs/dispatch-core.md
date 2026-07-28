# Spec: Dispatch core

**Status:** Implemented (gate green)
**Capability:** Dispatch core (`bess.assets`, `bess.validation`, `bess.optimizer`)
**Phases:** R1.1 deterministic core (2026-06-24), R1.2 degradation (2026-06-25,
regrounded to the linear model 2026-07-13), R1.3 pre-flight feasibility (2026-06-26)
**Depends on:** nothing; this is the base of the project

*Consolidated on 2026-07-28 from three work orders. They were one design delivered in
three passes: the wear cost is a term added to the objective, and the feasibility test
is an algebraic corollary of the physics. The phase boundaries recorded when each was
built, not a separate decision, so the spec now reads as the single thing it is.*

## Objective

Given a known price vector and a battery spec, return the optimal grid-side
charge/discharge schedule: a deterministic MILP maximizing arbitrage revenue **net of
cell wear**, under state-of-charge, power, mutual-exclusion, ramp, and terminal
constraints, with predictable infeasibility caught by an exact algebraic test
**before** the solver runs rather than surfacing as a stack trace.

## Formulation reference

Implements [formulation.md](../formulation.md) §R1.1 (deterministic core), §R1.2
(degradation cost), and §R1.3 (pre-flight feasibility) in full. **No math outside
those sections.**

Three invariants carry the design:

- Power is **grid-side**; efficiency lives in the SoC balance and never in the
  objective.
- Degradation is a **cost subtracted from revenue**; it never enters the SoC balance
  and adds no efficiency term to the cash flow.
- Pre-flight adds **no constraints, variables, or objective terms**. Its inequalities
  are corollaries of the SoC balance, the bounds, and the power limits. If the check
  and the derivation ever disagree, the formulation governs.

## Parameters / configuration

`BatterySpec` (Pydantic v2), defaults matching the sanity band (a 1-hour battery):

| Field | Default | Unit |
| --- | --- | --- |
| `capacity` ($e_{\max}$) | 1.0 | MWh |
| `soc_min` ($e_{\min}/e_{\max}$) | 0.0 | p.u. |
| `p_charge_max` | 1.0 | MW |
| `p_discharge_max` | 1.0 | MW |
| `eta_charge` | 0.95 | – |
| `eta_discharge` | 0.95 | – |
| `ramp` ($R$) | `None` (disabled) | MW/period |
| `soc_initial` ($e_0/e_{\max}$) | 0.0 | p.u. |
| `soc_terminal` ($e^{\mathrm{tgt}}/e_{\max}$) | 0.0 | p.u. |
| `degradation` | `None` | `DegradationSpec` |

**SoC fields are per-unit** (a fraction of `capacity`), per `conventions.md` §2 and
[per-unit SoC in config](../decisions/soc-per-unit-in-config.md): config is
size-independent, the model is absolute MWh. The asset converts at registration, and
`Schedule.soc` is reported in MWh. The full-charge bound is per-unit `1.0`. Power,
energy, and capacity stay MW and MWh.

`DegradationSpec` collapses to one field:

| Field | Meaning | Unit |
| --- | --- | --- |
| `cost_per_mwh` | marginal wear cost `c_deg` per unit storage-side throughput, `>= 0` | €/MWh |

Grounded values sit near €7 to €15/MWh (cell replacement cost divided by lifetime
throughput). `c_deg = 0` reduces to the no-wear model, as does `degradation=None`.

Prices and `dt` (default 1.0 h) are passed per solve, not stored on the spec.
Pre-flight itself has no configuration: it is pure logic over `(prices, spec, dt)`.

## The wear cost

Per-period **storage-side throughput**, counting both directions, and its linear cost:

```text
τ_t = η_ch · p_charge_t · dt  +  (p_discharge_t / η_dis) · dt
D_t = c_deg · τ_t
```

Efficiency appears in `τ_t` because it is cell-side energy, a wear quantity, not cash
flow, so a round trip of depth `q` is penalized on both its charge and its discharge
period. Because `Σ_t D_t = c_deg · Σ_t τ_t` is total energy through the cell times a
constant, the horizon cost is **independent of the time step**. That property is why
the linear form replaced the earlier convex-PWL basis, which was per unit of `τ_max`
and so coupled indirectly to `dt`. No `τ_max` is needed.

## The reachability test

Let `Δ = e^tgt − e_0` in absolute MWh. Per-period SoC increments are bounded by the
power limits and the balance:

```text
max charge step   Δ⁺ = η_ch · P̄_ch · dt
max discharge step Δ⁻ = (P̄_dis / η_dis) · dt
```

Over `T` periods the ramp-free condition is necessary and sufficient:

```text
Δ > 0  (must charge up):    Δ ≤ T · Δ⁺   else TERMINAL_UNREACHABLE_CHARGE
Δ < 0  (must discharge):   −Δ ≤ T · Δ⁻   else TERMINAL_UNREACHABLE_DISCHARGE
Δ = 0:                      always reachable (idle is feasible)
```

The endpoint box bounds are guaranteed by the Pydantic SoC-window validator, so
reachability is the only remaining feasibility question for the ramp-free model.

**Ramp interaction, stated rather than hidden.** With ramp enabled the inequalities
remain a **sound necessary** condition, since ramp only further restricts the
per-period swing, so an unreachable verdict is always correct. They are **not
sufficient** under a tight ramp: a ramp-coupled infeasibility can pass pre-flight and
is then caught by the solver's optimality guard. Pre-flight is a fast filter for the
provable class; the solver stays the final arbiter.

### What pre-flight does and does not catch

Pydantic already validates a `BatterySpec` at construction, so pre-flight does **not**
re-check the spec. Its value is the class of failures knowable only at solve time,
from the spec combined with the run inputs:

1. **Input hygiene:** empty horizon, any non-finite price, non-positive or non-finite
   `dt`.
2. **Terminal-SoC reachability:** the horizon length is unknown until solve time, so
   this cannot be a spec validator. It is the "selling energy the battery does not
   have" failure.

`validate` **accumulates** all issues rather than failing fast, so one call surfaces
every problem with the input.

## Interfaces

```python
# src/bess/assets/battery.py
class DegradationSpec(BaseModel):
    cost_per_mwh: float              # c_deg >= 0 (€/MWh storage-side throughput)

class BatterySpec(BaseModel):
    ...                              # fields per the table above
    degradation: DegradationSpec | None = None

class Battery:
    def register(self, model, prices: Sequence[float], dt: float) -> None: ...
    # adds variables + constraints (formulation §R1.1); when degradation is set,
    # attaches model.degradation_cost[t] as a Pyomo Expression equal to c_deg * τ_t.
    # No new Var, no epigraph cuts. When None, attaches nothing.

def schedule_degradation_cost(spec, p_charge, p_discharge, dt) -> float:
    # Σ_t c_deg · τ_t of a given dispatch (0 without a spec); scores a heuristic
    # schedule net of wear on the same basis as the solver.

# src/bess/optimizer/core.py
def build_model(prices, battery: BatterySpec, dt: float = 1.0): ...
def solve(prices, battery, dt=1.0, solver="appsi_highs") -> Schedule: ...
#   objective = Σ_t π_t·dt·(p_dis − p_ch) − Σ_t degradation_cost[t]
#   calls validation.check() as its first line, before build_model()

@dataclass
class Schedule:
    p_charge: list[float]            # grid-side MW per period
    p_discharge: list[float]         # grid-side MW per period
    soc: list[float]                 # MWh, end of each period
    objective: float                 # €

# src/bess/validation/preflight.py
class IssueCode(str, Enum):
    EMPTY_HORIZON                  = "empty_horizon"
    NON_FINITE_PRICE               = "non_finite_price"
    NON_POSITIVE_DT                = "non_positive_dt"
    TERMINAL_UNREACHABLE_CHARGE    = "terminal_unreachable_charge"
    TERMINAL_UNREACHABLE_DISCHARGE = "terminal_unreachable_discharge"

@dataclass(frozen=True)
class ValidationIssue:
    code: IssueCode
    input_field: str                 # "prices", "prices[3]", "dt", "soc_terminal"
    message: str                     # actionable; embeds the numbers
    context: dict[str, float | int]  # required, reachable, horizon, dt

class PreflightError(Exception):
    issues: list[ValidationIssue]

def validate(prices, spec: BatterySpec, dt: float) -> list[ValidationIssue]:
    """Pure. Returns ALL issues (possibly empty). Never raises, never solves."""

def check(prices, spec: BatterySpec, dt: float) -> None:
    """Raise PreflightError(issues) if validate() finds any; else return None."""
```

**Layering.** `validation` sits between `optimizer` and `assets` in the import chain:
`api → explain → stochastic → recourse → optimizer → validation → assets`. It imports
`assets.battery` for `BatterySpec`; `optimizer` imports it.

## Build tasks

- [x] `BatterySpec` config object with the defaults above; `DegradationSpec` with the
      single `cost_per_mwh` field.
- [x] `assets/` plugin interface; `Battery.register()` adds formulation §R1.1 to a
      Pyomo model, and the degradation `Expression` when configured.
- [x] `optimizer/core.py` `build_model()` + `solve()` (sense = maximize; HiGHS via
      `appsi_highs`), with the degradation term in the objective line.
- [x] `Schedule` return object.
- [x] `schedule_degradation_cost()` for scoring heuristic schedules on the same basis.
- [x] `validation/preflight.py`: `IssueCode`, `ValidationIssue`, `PreflightError`,
      pure `validate()`, `check()`; input-hygiene and reachability checks, accumulated.
- [x] Wire `check()` into `solve()` as the first step. `solve()` uses
      `load_solutions=False` so a residual ramp-coupled infeasibility returns a
      termination condition for the guard instead of raising on solution load.
- [x] import-linter contracts placing `assets`, `validation`, and `optimizer`.
- [x] Golden and property tests, written first and confirmed red.

**Retired by the 2026-07-13 regrounding**, and not to be reintroduced: the whole PWL
surface (`throughput_pu` / `cost_eur` breakpoints, `cost_at()`, `tau_max_mwh()`, the
`degradation_cost` **Var** with its `SEG` epigraph cuts, and the convex-PWL
non-negativity guard). `D_t = c_deg·τ_t ≥ 0` holds by construction.

## Golden oracles

Tolerance **`1e-6`** throughout. That sits above HiGHS's feasibility and optimality
tolerance (~`1e-7`) and float round-off, yet far below any economically meaningful
amount. It absorbs solver noise while still catching real formulation errors, and it
is **not** a knob to loosen when a test fails (CLAUDE.md §1).

### Dispatch and efficiency

1 MWh / 1 MW battery, `dt=1`, `e_0 = e^tgt = 0`, ramp disabled, `T=3` unless noted.

| # | inputs | expected objective | expected schedule | why this case |
| --- | --- | --- | --- | --- |
| 1 | $\pi=[10,50,20]$, $\eta=1$ | **40.0** | charge $[1,0,0]$; discharge $[0,1,0]$; soc $[1,0,0]$ | dispatch direction: buy low, sell high |
| 2 | $\pi=[10,50,20]$, $\eta=0.95$ | **35.125** | charge $[1,0,0]$; discharge $[0,0.9025,0]$; soc $[0.95,0,0]$ | efficiency placement (grid-side) |
| 3 | $\pi=[40,42,41]$, $\eta=0.95$ | **0.0** | all zero | declines a trade whose spread is below the round-trip loss |
| 4 | $T=2$, $\pi=[-1,-1]$, $\eta=0.95$ | **0.0975** | charge $[1,0]$; discharge $[0,0.9025]$ | negative prices: the battery profits as a *paid load*, not phantom profit |

**Derivation of oracle 2, the one to check by hand.** Charge $p^{ch}_1=1$ at price 10,
costing 10, giving $e_1=\eta^{ch}\cdot 1=0.95$. To empty by $t_3$, discharge
$p^{dis}_2$ with $p^{dis}_2/\eta^{dis}=0.95$, so $p^{dis}_2=0.9025$ at price 50, giving
revenue 45.125. Objective $=45.125-10=35.125$.

**Oracle 3.** A cycle pays only if $\eta^{rt}\pi^{sell} > \pi^{buy}$, so the price
ratio must exceed $1/\eta^{rt} = 1/0.9025 \approx 1.108$, a spread of about 10.8%. The
best pair here is buy at 40, sell at 42, only 5%, giving per grid-MWh cycled

$$\eta^{rt}\pi^{sell} - \pi^{buy} = 0.9025\cdot 42 - 40 = -2.095 < 0.$$

Every spread is loss-making after round-trip losses, so idle is optimal.

**Oracle 4, the negative-price subtlety.** With $e_0=e^{\mathrm{tgt}}$ and a single
equal price, energy balance forces $\sum_t p^{dis}_t = \eta^{rt}\sum_t p^{ch}_t$, so
the objective collapses to $\pi (\eta^{rt}-1)\sum p^{ch}$. For $\pi\ge 0$ this is
$\le 0$, so idle is optimal (oracle 3's regime). For $\pi<0$ it is $\ge 0$ and the
optimum charges at the cap: the battery is *paid* to consume the round-trip loss. Here
$1-0.9025=0.0975$. This is genuine, and distinct from the simultaneous
charge-and-discharge that the mutual-exclusion binary forbids.

### Wear

1 MWh / 1 MW, `dt=1`, `e_0 = e^tgt = 0`. A **linear** cost makes the cycle
**bang-bang**: with a constant per-MWh cost the trade is all-or-nothing, unlike the
retired PWL model's partial optimum.

| # | inputs | expected objective | expected schedule | why this case |
| --- | --- | --- | --- | --- |
| 5 | T=2, π=[0,50], η=1, c_deg=10 | **30.0** | charge [1,0]; discharge [0,1] | cheap wear: round-trip cost 20 below the spread 50, so a full cycle |
| 6 | T=2, π=[0,50], η=1, c_deg=30 | **0.0** | idle | expensive wear: 60 above the spread 50; breakeven at c_deg=25 |
| 7 | T=2, π=[0,50], η_ch=1, η_dis=0.8, c_deg=10 | **20.0** | charge [1,0]; discharge [0,0.8] | storage-side: τ is cell-side, so discharge τ = p_dis/η_dis = 1, not 0.8 |
| 8 | T=3, π=[10,50,20], degradation=None | **40.0** | as oracle 1 | regression: disabled means exactly the no-wear model |

**Oracles 5 and 6, bang-bang.** Terminal 0 forces discharge = charge = `q`; at `η=1`,
`τ=q` per period, so `f(q) = 50q − 2·c_deg·q`, linear in `q ∈ [0,1]`. A positive slope
(`c_deg < 25`) gives `q*=1`; negative (`c_deg > 25`) gives `q*=0`.

**Oracle 7, storage-side.** Charge `q` at price 0 gives `soc_0 = q` and charge-side
`τ_0 = q`. Discharging to terminal 0 gives `p_dis = 0.8q` and discharge-side
`τ_1 = p_dis/η_dis = q`. Revenue is `40q`, degradation `2·c_deg·q`, so
`f(q) = (40 − 2·c_deg)·q` and at `c_deg=10` the optimum is `q*=1`, objective **20**. A
grid-side implementation would score discharge throughput as `0.8` rather than `1`,
giving `f = (40 − 1.8·c_deg)·q` and objective **22**: that is the number this oracle
pins.

### Pre-flight

Pure, so each oracle pins an exact issue set by code. Defaults are the 1 MWh / 1 MW
spec at `dt=1` unless noted.

| # | inputs | expected codes | why this case |
| --- | --- | --- | --- |
| 9 | oracle 1's input | `[]` | good input passes clean; pre-flight never blocks a valid solve |
| 10 | `prices=[]` | `[EMPTY_HORIZON]` | no periods to dispatch |
| 11 | `π=[10, NaN, 20]` | `[NON_FINITE_PRICE]`, field `prices[1]` | dirty data caught with the offending index |
| 12 | `dt=0`, `π=[10,50]` | `[NON_POSITIVE_DT]` | zero or negative period length is nonsensical |
| 13 | `T=1`, `soc_initial=0`, `soc_terminal=1.0`, `p_charge_max=0.5`, `η_ch=1` | `[TERMINAL_UNREACHABLE_CHARGE]`, context `required=1.0, reachable=0.5` | needs +1.0 MWh; one period charges at most 0.5 |
| 14 | `T=1`, `soc_initial=1.0`, `soc_terminal=0`, `p_discharge_max=0.5`, `η_dis=1` | `[TERMINAL_UNREACHABLE_DISCHARGE]`, `required=1.0, reachable=0.5` | needs −1.0 MWh; one period removes at most 0.5 |
| 15 | `T=2`, `soc_initial=0`, `soc_terminal=1.0`, `p_charge_max=0.5`, `η_ch=1` | `[]` | **boundary**: two periods reach exactly 1.0; equality is feasible |
| 16 | `dt=0` **and** `π=[10, inf]` | `[NON_POSITIVE_DT, NON_FINITE_PRICE]` | accumulation: one call reports every issue |

Issue **ordering** is fixed by this spec so the assertions are deterministic: hygiene
checks run in input order (`dt`, then prices left to right), then reachability.

## Property tests

Over random valid price vectors and specs.

**Physics.**

- **SoC bounds:** $e_{\min}\le e_t \le e_{\max}$ every period.
- **Power caps:** $0\le p^{ch}_t\le \bar P^{ch}$, $0\le p^{dis}_t\le \bar P^{dis}$.
- **Mutual exclusion:** never both $p^{ch}_t>\epsilon$ and $p^{dis}_t>\epsilon$.
- **SoC continuity, exact:** $e_t \approx e_{t-1}+\eta^{ch}p^{ch}_t\Delta t - p^{dis}_t\Delta t/\eta^{dis}$.
- **Terminal:** $e_T \approx e^{\mathrm{tgt}}$.
- **Ramp, when enabled:** $|p^{net}_t-p^{net}_{t-1}|\le R+\epsilon$.

**Economics.**

- **Objective consistency:** solver objective $\approx \sum_t \pi_t \Delta t (p^{dis}_t-p^{ch}_t) - c_{deg}\sum_t \tau_t$.
- **Objective floor:** objective $\ge -\epsilon$ always, since idle is feasible.
- **No phantom profit:** if every price is equal **and non-negative**, the objective is
  $\le \epsilon$. The bound is restricted to non-negative prices because under
  uniformly negative prices the battery legitimately profits as a paid load; see
  oracle 4.
- **Step-size invariance, the headline linear property:** for a fixed physical
  dispatch, total degradation is equal at `dt=1` and `dt=0.25`, because it is
  `c_deg × total cell throughput`, independent of the time partition.
- **Monotone:** `c_deg ≥ 0`, so more throughput never lowers cost and a higher
  `c_deg` never raises the objective.
- **Degradation never pays:** objective with wear ≤ objective without, same prices.
- **Reduces to the no-wear model** at `c_deg = 0` and at `degradation=None`.
- **Scale invariance:** `c_deg` is €/MWh, so scaling the asset's power and energy
  together leaves the marginal wear cost unchanged.

**Pre-flight.**

- **Total and pure:** `validate` never raises and always returns a list, for arbitrary
  prices (including `NaN`, `inf`, empty), arbitrary `dt` (including 0, negative,
  non-finite), and any valid spec.
- **Soundness, no false positives, ramp on or off:** if `validate` emits an
  unreachable code, `solve` does not reach optimality on the same input.
- **Completeness, ramp-free:** with ramp disabled and otherwise-clean inputs, no
  reachability issue implies `solve` reaches optimality.
- **Integration:** `solve` raises `PreflightError` **iff** `validate` returns a
  non-empty list, and no schedule is produced when it does.
- **No regression:** on the inputs the physics and economics strategies exercise,
  `validate` returns `[]`.

## Acceptance gate

*Blocks:* everything. This is the base every other capability solves against.

- [x] All sixteen golden oracles match within `1e-6` (codes, fields, and contexts as
      asserted for the pre-flight set).
- [x] Physics property tests green at 200 Hypothesis examples.
- [x] Economics property tests green: step-size invariance, objective consistency,
      monotonicity, never-pays, reduces-to-no-wear, scale invariance.
- [x] Pre-flight property tests green: purity @200, soundness @200 (ramp on and off),
      ramp-free completeness @200, integration @150, no-regression @100.
- [x] `solve()` raises a structured `PreflightError`, never a solver stack trace or a
      bare `RuntimeError`, on the predictable infeasibility class; the residual
      ramp-coupled class is still caught by the optimality guard.
- [x] No residual PWL surface: `throughput_pu`, `cost_eur`, `cost_at`, `tau_max_mwh`,
      and the epigraph cuts are gone; grep clean across `src/`, `tests/`, `examples/`,
      and `docs/`.
- [x] import-linter reports every contract KEPT.
- [x] `ruff check`, `ruff format --check`, and docs-lint clean.

## Out of scope

- **Nonlinear convex depth-of-discharge stress** ($\Phi(d)=k_2 d e^{k_3 d}$ or
  $k_4 d^{k_5}$): the more accurate model, capturing the deep-cycle penalty, since an
  NMC cell loses roughly ten times more life at 100% depth than at 10%. It is convex
  in the SoC profile but needs rainflow cycle identification, which has no closed
  form, so it is convex yet **not LP-representable**. The sources and the convexity
  result are in formulation §R1.2 and [references.md](../references.md); referenced
  future work.
- **The retired convex-PWL cost on per-period throughput. Do not re-add.** It
  penalized instantaneous power rather than cycle depth, so it matched no published
  source.
- **Rainflow cycle counting** and **calendar aging**: path-dependent and
  time-dependent respectively, different in kind from a per-period cost. Deferred,
  not faked.
- **Equivalent-full-cycle normalization** and **direction-specific wear curves**:
  reparametrizations that only earn their place against real cycle-life data.
- **Ramp-aware reachability.** Only the ramp-free necessary condition is checked;
  ramp-coupled infeasibility stays with the solver guard.
- **Severity tiers.** One blocking tier only. A non-blocking warning class is deferred
  until one actually appears.
- **Surfacing issues or per-period wear in `Schedule`.** `Schedule` is unchanged;
  pre-flight either passes or raises.
- **Physics fidelity beyond a constant-efficiency cell**: no self-discharge, no
  temperature or SoC-dependent effects. The reasoning is in formulation §R1.1's
  modeling notes: on a day-ahead horizon the price-forecast error dwarfs the
  battery-model error, and the tempting refinements are non-convex.

## Decisions

**Physics and solve (2026-06-24).**

1. **Period resolution.** **Resolved:** `dt` stays a per-solve argument; the core's
   oracles are hourly, and quarter-hourly input is handled at the data layer, not by
   the core.
2. **Solver entry point.** **Resolved:** `appsi_highs`, the Pyomo APPSI HiGHS
   interface, as the default `solver=` argument.
3. **Default battery.** **Resolved:** 1 MW / 1 MWh, matching the
   [sanity band](../formulation-evaluation.md#sanity-band-gate-d). A different
   duration is a per-spec override, needing no core change.

**Wear (2026-07-13, at the regrounding).**

4. **Config shape.** **Resolved:** keep the `DegradationSpec` wrapper with one field
   rather than a bare float, which preserves the `None` means no-wear plumbing,
   self-documents the €/MWh unit, and leaves room for a second parameter later.
5. **How the cost reaches the objective.** **Resolved:** `Battery.register` attaches
   an `Expression`, so the objective line in `core.py` is unchanged and stays agnostic
   to whether the term is a Var (as in the retired model) or an Expression.
6. **`tau_max_mwh` removal.** **Resolved:** remove it; the linear cost needs no
   `τ_max`, and the only call sites were degradation's own.

**Pre-flight (2026-06-26).**

7. **Should `solve()` auto-run pre-flight?** **Resolved: yes**, fail-closed as the
   first line, so no caller can reach the solver with provably-bad input. The
   alternative, keeping `optimizer` pure and requiring the serving layer to call
   `check()`, lets any other caller bypass the guard. The cost is one edge in the
   layer chain, which is clean.
   *Is auto-run wasteful?* Not on cost: `validate()` is O(T), a finiteness scan plus
   O(1) arithmetic, guarding a build-and-solve that is orders of magnitude more
   expensive. The real case is **redundancy**, in layers that re-solve the same
   horizon many times (intraday recourse, scenario ensembles) and so re-scan unchanged
   input. If a profile ever attributes real time there, add a scoped bypass for
   trusted internal callers, **not** a removal of the guard. Do not pre-optimize.
8. **Layer placement.** **Resolved:** insert `validation` between `optimizer` and
   `assets`. The alternative, a sibling utility imported by both the serving layer and
   the optimizer, weakens the linear chain.
9. **`prices` type.** **Resolved:** accept any `Sequence[float]`, with non-finite
   detection via `math.isfinite`. Pandas and numpy series arrive at the data layer,
   which hands clean floats to the optimizer.
