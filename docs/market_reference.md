# Market reference — Belgium & Netherlands

Domain reference for the BE and NL power markets: *what the market does*. This is a **knowledge artifact**, not a build spec — [`formulation.md`](formulation.md) and the phase specs define what the code actually models.

> **Scope flags.** Only the **day-ahead** market is in build scope for Release 1–2. FCR, aFRR, imbalance, and intraday are **reference only** — kept here for correctness of reasoning, interview readiness, and possible future work. Build scope is marked per section.

> **Verification notice.** Market mechanics evolve. Cross-check every rule and parameter against current EPEX SPOT, TenneT, and Elia publications before implementing or trusting it. Key sources are listed at the end. Knowledge here is current as of early 2026.

---

## 1. Actors

| Role | Netherlands | Belgium |
|---|---|---|
| TSO | TenneT TSO B.V. | Elia |
| Regulator | ACM | CREG (federal) |
| Day-ahead / intraday exchange | EPEX SPOT | EPEX SPOT (formerly Belpex) |
| Open-data portal | TenneT Open Data | Elia Open Data |

Both zones clear day-ahead through **SDAC** (Single Day-Ahead Coupling) with cross-zonal capacity allocated by **Flow-Based Market Coupling** in the **CORE** region. EU balancing platforms **PICASSO** (aFRR energy) and **MARI** (mFRR) apply to both.

---

## 2. Time anchoring

- **CET / CEST** (UTC+1 / UTC+2) is the operational timezone. The codebase stores all timestamps in **UTC** and applies CET only at display — see `docs/conventions.md`.
- **Imbalance Settlement Period (ISP):** 15 minutes, aligned to clock quarters, in both zones.
- **Day-ahead Market Time Unit (MTU):** **15 minutes since 1 October 2025** (96 quarter-hours per delivery day) across all SDAC bidding zones including BE and NL. Hourly was the historical resolution; a 60-minute index is still published as the average of the 15-minute clearing prices.

---

## 3. Day-ahead market — **[BUILD SCOPE: Release 1–2]**

### Mechanism
The EPEX SPOT day-ahead auction. Price-volume bids clear at the marginal price via the pan-European EUPHEMIA algorithm; cross-border capacity is allocated implicitly under flow-based coupling.

### Key parameters
- **Gate closure:** 12:00 CET on D-1; results ~12:55 CET.
- **Resolution:** 15-minute MTU (96 periods/day) since 2025-10-01 delivery. Hourly/30-min bids still accepted (cross-product matching), but the clearing and price series are 15-minute.
- **Negative prices:** allowed and increasingly frequent with high renewable penetration.
- **Currency:** EUR/MWh.

### Modelling implications
- The optimizer's price input is the cleared day-ahead curve, treated as **known and deterministic** once published (D-1 after 12:00 CET). This is the deterministic core of Release 1.
- **Resolution choice:** the *real* series is 15-minute. R1.1's hourly core (`Δt = 1.0`) is a deliberate simplification for the first correctness pass; the backtest (R1.4) and everything downstream should run on the native 15-minute series (`Δt = 0.25`, 96 periods/day). Keep `Δt` an explicit parameter everywhere so the switch is a config change, not a rewrite.
- A storage-specific SDAC order type (lets storage bid without detailed forecasts) is planned for a future delivery — track it as possible future work, do not model it now.

### Data
ENTSO-E Transparency Platform, `entsoe-py` method `query_day_ahead_prices`, area codes `10YNL----------L` (NL) and `10YBE----------2` (BE). Confirm the current token process at build time.

---

## 4. FCR — Frequency Containment Reserve — **[REFERENCE ONLY]**

Symmetric automatic primary reserve; responds to frequency deviation by droop, full activation at ±200 mHz within 30 s, sustained for **15 minutes** (this drives the SoC-headroom requirement). Procured daily via the cross-border platform (regelleistung.net), **4-hour blocks**, marginal (pay-as-cleared) pricing, EUR/MW/h, capacity-only (no energy revenue). Modelling note: a reserved `p_fcr` MW requires `p_fcr × 0.25 MWh` of SoC headroom on both sides. **Symmetry:** up = down per block. *Interview-relevant; not built.*

---

## 5. aFRR — automatic Frequency Restoration Reserve — **[REFERENCE ONLY]**

TSO-dispatched secondary reserve, AGC setpoint at 4-second resolution, full activation within 5 minutes. Procured **up (POS)** and **down (NEG)** separately (asymmetric allowed), D-1 capacity auction in 15-min products, plus **energy** payment for activated MWh cleared marginally via **PICASSO**. Two revenue streams (capacity + activation). Activation prices can be negative (down-activation in oversupply). Modelling would require an activation-fraction model calibrated from TSO data. *Not built.*

---

## 6. Imbalance settlement — **[REFERENCE ONLY]**

Real-time settlement of deviations per 15-min ISP at the TSO-published imbalance price. A BESS can take a **passive** imbalance position (deliberately over/under-deliver vs. its day-ahead schedule when the imbalance price is favourable) — effectively a form of trading. Imbalance prices are highly volatile and heavy-tailed (scarcity spikes to regulatory ceilings). **BE vs NL differ:** NL uses a single-price-per-ISP system with corrections; BE uses a single imbalance price with an additional incentivising **alpha** component during large system imbalance — verify both against current TenneT/Elia rules. This is the market the recourse layer (R2.3) could eventually settle against; it is *not* the day-ahead arbitrage the core models. *Not built in Release 1–2.*

---

## 7. Intraday continuous — **[REFERENCE ONLY]**

EPEX SPOT continuous trading, opens ~15:00 CET on D-1, runs until ~5 min before delivery; price is whatever counterparties agree. A real revenue stream for sophisticated operators but requires a continuous-trading simulator. The R2.3 recourse layer re-optimizes against *realized day-ahead* prices on a rolling horizon — it does **not** simulate intraday continuous trading. Acknowledge intraday as a foregone stream in any report. *Not built.*

---

## 8. Gate-closure sequence (matters for the recourse layer)

```
 FCR ──► aFRR-cap ──► DAY-AHEAD ──► intraday ──► aFRR-energy
 D-1      D-1 ~09:00   D-1 12:00 CET   D-1 15:00     real-time
 morning  CET          (build scope)   → pre-delivery
```

In a single-pass perfect-foresight solve this ordering is invisible. In the **rolling-horizon / recourse** model (R2.3) the order matters: each later decision is constrained by earlier firm commitments. For the day-ahead-only scope, the relevant fact is simply that the full 24h (96-period) schedule is committed at the 12:00 CET gate — which is exactly why a naive single-shot stochastic model has no recourse value (see the VSS discussion in the [`formulation.md`](formulation.md) R2.3 section, when written).

---

## 9. Data sources

| Source | Use | Access |
|---|---|---|
| ENTSO-E Transparency | DA prices (BE/NL), load, generation | `entsoe-py`, free token |
| Elia Open Data | BE imbalance, system imbalance, solar/wind | Open portal / API |
| TenneT Open Data | NL imbalance, settlement | Open portal |
| EPEX SPOT | DA/intraday reference, methodology | Public + licensed |

**Reproducibility:** commit a small real fixture slice so the test suite runs without a token; document the token process for full backtests. Check redistribution terms before committing data.

---

## Sources & verification

- EPEX SPOT — 15-minute MTU go-live in SDAC, 30 Sep 2025 (delivery 1 Oct 2025); 60-minute index = average of 15-min prices.
- ENTSO-E — SDAC / CACM implementation; Transparency Platform API.
- TenneT (NL) and Elia (BE) — balancing products, imbalance pricing, open data.
- regelleistung.net — FCR/aFRR cross-border procurement.

Re-verify FCR/aFRR parameters, imbalance pricing mechanics, and the 15-min rollout details against these before relying on any specific number.
