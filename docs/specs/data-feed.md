# Spec: Data feed

**Status:** Implemented (gate green)
**Capability:** Data feed (`bess.data`)
**Phases:** R1.4b ENTSO-E loader (2026-06-26), R1.4c ingestion guard (2026-07-01)
**Depends on:** R1.4a (the price-series schema this produces)

*Consolidated on 2026-07-28 from two work orders: the loader that fetches real prices
and the guard that decides whether to trust them. They are one module and one
question, "can this price series be used", answered at two levels.*

## Objective

A productionized ENTSO-E **day-ahead loader** producing the internal price-series
schema the backtest already consumes, pulling real BE/NL history token-gated with
on-disk caching; and a **second circuit breaker** wrapping the *fetch* rather than the
solve, which classifies every fetch as `healthy`, `outage`, or `anomaly`, never lets a
corrupted-but-present series reach the optimizer unflagged, and falls back to the
last-known-good series on either failure.

Together they close the failure mode a dispatch platform is most exposed to: **the
feed silently lied to the algorithm.**

## Formulation reference

**None. No new math.** This is data acquisition and integrity over the existing
loader: no constraint, objective term, or efficiency placement changes. The internal
schema is the one `validate_price_series` already enforces (UTC, sorted, regular,
gap-free).

## Governing decisions

Recorded in `docs/decisions/`, not restated here:

- [Two separate circuit breakers with one shared vocabulary](../decisions/separate-ingestion-breaker.md).
  Two breakers and two taxonomies rather than one generic wrapper, so an operator sees
  *which layer* failed; and a shared degradation vocabulary so a solve on stale prices
  is never reported as plainly healthy. It also draws the pre-flight line: pre-flight
  asks *is this problem solvable*, the guard asks *can this data be trusted*.
- [No committed market data](../decisions/no-committed-market-data.md). Synthetic
  fixtures gate CI; real history is fetched at runtime and never committed.

## Verified API facts

Fetched and inspected before coding against it (CLAUDE.md §7), not written from memory:

- **Host** `https://web-api.tp.entsoe.eu/api`, note `tp` not `tps`; the old host no
  longer resolves. Auth by `securityToken` query param. Rate limit 400 req/min/IP.
- **Day-ahead prices:** `documentType=A44`, `in_Domain`/`out_Domain` the zone EIC
  (NL `10YNL----------L`, BE `10YBE----------2`), `periodStart`/`periodEnd` as
  `YYYYMMDDHHMM` UTC.
- **Response:** `Publication_MarketDocument` → one `TimeSeries` per market day →
  `Period` with `resolution` (`PT60M` for 2024 NL, `PT15M` after the 2025-10 switch) →
  `Point`s with **1-based `position`** and `price.amount`; `timeInterval` in UTC.
- **Curve quirk, must handle:** A03 curves **omit a `Point` when the price is
  unchanged**, so a missing position carries the previous price forward. The loader
  expands positions to a full regular series.
- **Feed sanity:** probed NL prices matched published EPEX/ENTSO-E values, confirming
  the parser targets the right series.

**Environment, operator setup rather than code.** A TLS-intercepting proxy with a
private CA sits on this network: `curl` trusts it via the macOS Keychain but the
bundled Python does not, so HTTPS to ENTSO-E fails certificate verification. The fix
is to point Python at the Keychain roots via `REQUESTS_CA_BUNDLE` and `SSL_CERT_FILE`,
documented in `.env.example`. **The loader must not hard-code a CA path.** CI never
hits the API and is unaffected.

## The anomaly checks

The classifier's job is discrimination, and the sharp domain trap is that **zero and
negative prices are legitimate** in BE/NL day-ahead markets. A naive "flag €0.00 or
flag negatives" check would misclassify real market conditions as corruption and fall
back to stale prices, causing the exact bad dispatch it exists to prevent. The checks
therefore key on **feed pathology, not price level**:

| # | Check | Fires on | Deliberately does **not** fire on |
| --- | --- | --- | --- |
| 1 | **Stuck feed** (shape-aware) | ≥ `max_repeat` consecutive bit-identical values at an *arbitrary* price, or ≥ `max_focal_repeat` at a **focal** price | a real low/zero/negative price that still *varies*; and a long run at a focal price, which is market behaviour |
| 2 | **Out-of-band** | value outside `[-600, 5000]` €/MWh | anything inside the band, including legitimate negatives and zeros |
| 3 | **Non-finite** | any `NaN` or `±inf` | – |
| 4 | **Structural** | timestamp gap, duplicate timestamp, non-UTC or unsorted index, **resolution change** (named separately) | a regular gap-free series |
| 5 | **Empty / short** | zero points, or fewer than `expected_slots_per_day` **when the caller supplies it** | a full day, and any legitimate partial-window fetch |

**Outage** is decided before any content check: timeout, connection error, HTTP 5xx,
or an empty body. Distinct by construction, since an outage means *no present data*
while an anomaly means *present but untrustworthy data*.

The band is grounded in the **EPEX SDAC harmonised clearing-price limits** (min −600
€/MWh from 2026-05-28, max 4000 €/MWh base, which can be raised in +1000 steps), with one
escalation step of headroom. A value outside it *cannot be a real clearing price*, so
it is corruption by definition. This is a market technical bound, **not** the
year-specific [sanity band](../formulation-evaluation.md#sanity-band-gate-d): it does
not move with volatility, only if SDAC changes its limits.

### Why the stuck-feed check keys on the price, not the run length

A bit-identical run means the market cleared at the *same cent* repeatedly, which is
only plausible at a **structural focal point** of the bid stack where the merit order
has a genuine flat step. Two exist: **€0.00**, the natural zero bid that excess supply
collapses onto, and the **SDAC floor or cap**, which the price cannot cross and pins
against under scarcity. At any other value prices move continuously and are quoted to
the cent, so an arbitrary value recurring for hours has negligible probability.

**Measured, not assumed** (NL and BE, full-year 2024): every run of 3 h or more sits
at `|p| ≤ €0.01` (8 h and 7 h at 0.00, 3 h at 0.00, 3 h at −0.01), while runs at
arbitrary values never exceed **2 h**. Negative prices below zero are a different
regime, must-run units paying to stay on, and vary continuously: −50.00, −39.79 and
−27.30 are all distinct. Also measured: NL and
BE 2025 to the PT15M switch (nothing ≥ 6 h), and NL Nov 2025 at PT15M (longest 0.75 h,
at an arbitrary value).

A tempting alternative, **rejected on the data**: "a legitimate flat run sits at the
bottom of its day's range." The 7 h zero run on 2024-04-07 sits at the **33rd
percentile** of its day, whose minimum was −50.00, so position-in-range does not
separate the cases. Only the value does.

**This strictly dominates the length-only rule it replaced.** Against the real
2024-03-24 day an 8 h threshold classified genuine prices as `stuck_feed`, and pushing
it to 12 h to clear that run left an arbitrary-value freeze undetected for 11 h. Keying
on the value removes the false positive *and* tightens detection: a freeze at €73.07 is
caught in **4 h**, three times faster, because the non-focal bound no longer has to
admit the zero run.

**Known limit.** The focal allowance is still a length cap, so a focal price is not
licensed indefinitely: a full day pinned at exactly €0.00 is an all-zeros feed, not a
market, and fires. Real NL/BE zero runs peaked at 8 h in 2024 and grow with solar
buildout, so `max_focal_flat_hours` is the number to revisit; the integration test
measures it.

### A resolution change is not a gap

A window straddling an MTU change (the 2025-10 switch from PT60M to PT15M) is
genuinely irregular, so the guard is right to refuse it: the engine cannot consume a
mixed-resolution series. But **nothing is missing**, so reporting `schema:gap` sent an
operator hunting for timestamps that were never absent. `classify_series` names it
`schema:resolution_change`: two contiguous segments, each internally regular, at
different steps, each at least 4 slots long. The real 2025-10 event was 46 hourly
steps followed by 104 quarter-hourly ones. The discriminator is deliberately
conservative, and anything that is not cleanly two long regimes stays a `gap`. Both
classify ANOMALY either way, so a misnamed edge case costs a log line rather than a
wrong decision.

The **status stays ANOMALY** deliberately: the effect is right (do not consume, fall
back), and a fourth status for a once-a-decade market event would ripple through the
shared vocabulary to buy a word.

**Reason tokens carry a diagnosis, not a Python type.** The fetch-path schema arm
reports `schema:invalid` plus the validator's message as `detail=`. It previously used
`type(exc).__name__`, reporting `schema:valueerror` for every cause and discarding the
only text that said which rule fired: the same conflation the two-breaker decision
exists to prevent, one level down.

### Why `expected_slots_per_day` is caller-supplied

Deriving it from the series resolution and always applying it would turn every
legitimate **partial-window** fetch into a `short` anomaly: asking for six hours and
getting six hours back is a correct answer. The guard cannot tell a deliberately short
window from a truncated one, because only the *caller* knows what it asked for. So the
check is opt-in, and the caller that does know enforces coverage instead:
`fetch_day_ahead` rejects a series that does not span its requested window. This is a
deliberate division of labour; **do not "fix" it into a false positive.**

## Parameters / configuration

| Item | Where | Default |
| --- | --- | --- |
| `ENTSOE_API_TOKEN` | `.env`, gitignored | secret |
| zones | EIC map | `NL`, `BE` |
| resolutions | derived from the feed | `PT60M`, `PT15M` (`dt` 1.0 / 0.25) |
| cache | parquet under `data/cache/`, gitignored | per zone/window |
| `BESS_CACHE_DIR` | env | supplies `cache_dir` when a caller passes none; unset means no cache |
| `sanity_band` (lo, hi) €/MWh | guard config, env-overridable | `(-600.0, 5000.0)` |
| `max_flat_hours` (non-focal) | guard config | `4.0` wall-clock hours |
| `max_focal_flat_hours` (focal) | guard config | `24.0` wall-clock hours |
| `FOCAL_PRICE_EPS` | module constant | `0.01` €/MWh; prices are quoted to the cent |
| `expected_slots_per_day` | caller-supplied | `None`, which disables the check |

Stuck-feed thresholds are expressed in **wall-clock hours**, not slot counts, so they
survive the 60-to-15-minute resolution switch (`max_repeat = ceil(hours / dt_hours)`):
the non-focal bound resolves to 4 slots at 60-minute and 16 at 15-minute resolution,
the focal bound to 24 and 96. A full day is 24 or 96 slots accordingly.

## Interfaces

```python
# src/bess/data/entsoe.py            (data stays a leaf: no other bess imports)
def fetch_day_ahead(
    zone: str, start: pd.Timestamp, end: pd.Timestamp, *,
    api_token: str | None = None,    # default: os.environ["ENTSOE_API_TOKEN"]
    cache_dir: Path | None = None,   # parquet cache; default $BESS_CACHE_DIR, else none
) -> pd.Series:                      # UTC, price_eur_mwh, regular, gap-free
    ...

def parse_day_ahead_xml(xml_text: str) -> pd.Series:
    """Token-free A44 -> internal schema; the golden parser test's entry point."""

# src/bess/data/ingestion_guard.py
class FeedStatus(str, Enum):
    HEALTHY = "healthy"
    OUTAGE  = "outage"
    ANOMALY = "anomaly"

@dataclass(frozen=True)
class GuardResult:
    status: FeedStatus
    prices: pd.Series      # HEALTHY -> the fetched series; degraded -> last-known-good
    reason: str | None     # stable token, found with grep: "stuck_feed" |
                           #   "non_finite" | "empty" | "schema:gap" |
                           #   "schema:resolution_change" | "schema:tz" |
                           #   "schema:duplicate" | "schema:unsorted" | "schema:index"
                           #   (classifier path); "schema:invalid" (fetch path, with the
                           #   validator's message logged as detail=); "timeout" |
                           #   "connection" | "transport" (outage)
    degraded: bool         # True when status != HEALTHY

def is_focal_price(value: float, sanity_band=(-600.0, 5000.0)) -> bool:
    """Is `value` a structural focal point the market plausibly clears at repeatedly?
    Zero (the natural zero bid) or either technical band edge."""

def classify_series(series, *, sanity_band, max_repeat, max_focal_repeat,
                    expected_slots_per_day) -> tuple[FeedStatus, str | None]:
    """Pure content classifier over an already-fetched series. HEALTHY or ANOMALY only;
    transport is decided before this runs. No I/O: the core that cannot be faked."""

def guarded_fetch(fetch_fn, *, last_known_good, sanity_band=(-600.0, 5000.0),
                  max_flat_hours=4.0, max_focal_flat_hours=24.0,
                  expected_slots_per_day=None) -> GuardResult:
    """Fetch -> classify -> (fallback + log) -> GuardResult. Never raises on a bad
    feed: outage and anomaly both fall back and are logged with the reason. Raises only
    if a fallback is needed and none exists (a genuine hard stop)."""
```

`fetch_day_ahead` wraps **entsoe-py**, which owns EIC mapping, XML parsing, the A03
carry-forward expansion, and 60/15-minute handling, then normalizes to the internal
schema and validates it. `guarded_fetch` owns the try/except: transport exceptions
become `OUTAGE`, a validator `ValueError` becomes `ANOMALY(reason="schema:…")`, and
otherwise `classify_series` runs on the valid series.

## Build tasks

- [x] Add `entsoe-py`; add `.env.example`; document the CA-bundle setup.
- [x] `fetch_day_ahead` (entsoe-py wrapper, internal schema, parquet cache). Rejects a
      series that does not span the requested window.
- [x] **Hand-crafted synthetic** A44 XML for the parser test, not a real download. It
      encodes the real *structure* (1-based positions, a carried-forward gap, `PT60M`,
      UTC); the prices are fabricated. Inline in the test; no file is committed.
- [x] Token-free parser test: synthetic XML to internal schema, asserting UTC, hourly,
      gap-free, and correct position expansion including the carried-forward gap.
- [x] `ingestion_guard.py`: `FeedStatus`, `GuardResult`, `classify_series` (checks 1
      to 5), `guarded_fetch` (transport/anomaly split, fallback, structured logging).
- [x] Reconcile with `validate_price_series`: catch its `ValueError` and map it to
      `ANOMALY`, so structural faults become a *classification* rather than a crash.
- [x] Structured logging, one line per non-healthy fetch with `{status, reason,
      degraded}`, so outage and anomaly are grep-distinguishable.
- [x] Route the backtest and example fetch path through `guarded_fetch`, so the shared
      provenance composition is exercised on a real chain rather than asserted.
- [x] `@pytest.mark.integration` marker, skipped without token and network.
- [x] Token-gated live checks: both stuck-feed bounds against a **full year** of NL and
      BE, the band watchdog on the last complete month, the real 2025-10 SDAC switch
      labelled `schema:resolution_change`, and the sanity band on real Q1 versus a
      volatile summer slice. Nothing fetched is committed.

## Golden oracles

**Loader.** The synthetic XML parses to a known first/last timestamp and price vector,
with positions expanded correctly including at least one carried-forward gap.
`fetch_day_ahead` output passes every schema validation, and raises if the returned
series does not span the requested window. Regularity alone cannot catch truncation: a
fetch cut short at either end stays regular, has no interior gap, and validates clean.

**Guard.**

| # | input feed | expected status / reason | why this case |
| --- | --- | --- | --- |
| 1 | clean synthetic day | `HEALTHY` / `None` | good data passes through untouched |
| 2 | day frozen at an **arbitrary** price (€73.07) ≥ `max_repeat` | `ANOMALY` / `stuck_feed` | the market does not clear at the same arbitrary cent for hours |
| 2b | **same-length** block at the **€0.00 focal price** | `HEALTHY` / `None` | the pair to oracle 2, and the whole point: NL *and* BE cleared at €0.00 for 8 h on 2024-03-24, so length alone cannot separate these |
| 2c | a full day ≥ `max_focal_repeat` pinned at €0.00 | `ANOMALY` / `stuck_feed` | focal is not unbounded: an all-zeros feed is not a market |
| 2d | block at the **band edge** ≥ `max_repeat` | `HEALTHY` / `None` | a scarcity pin is structural, not a freeze |
| 3 | one interior timestamp slot removed | `ANOMALY` / `schema:gap` | a structural fault surfaced as a classification, not a crash |
| 3b | window straddling PT60M to PT15M | `ANOMALY` / `schema:resolution_change` | still refused, but not called a gap |
| 3c | two *adjacent* slots removed | `ANOMALY` / `schema:gap` | the discriminator is conservative |
| 4 | a single €9999 point | `ANOMALY` / `out_of_band` | an implausible spike caught by the wide band |
| 5 | **legitimate** low day: negatives and zeros that still **vary** | `HEALTHY` / `None` | the domain trap; a real solar-glut day must not be flagged |
| 6 | `fetch_fn` raises a timeout | `OUTAGE` / `timeout`, `degraded=True`, prices are the fallback | transport failure falls back and is labelled outage |

## Property tests

- **No corrupted series ever passes as healthy:** for any injected fault (arbitrary
  freeze, over-long focal freeze, gap, duplicate, out-of-band, `NaN`), the status is
  not `HEALTHY`.
- **No false positives:** any schema-valid, fault-free series with arbitrary in-band
  prices, including negatives and zeros that vary, is `HEALTHY`.
- **No false positive on a focal run:** a bit-identical €0.00 run of any length inside
  `max_focal_repeat` is `HEALTHY`. This is the pair to the first invariant.
- **Outage is disjoint from anomaly:** transport-shaped failures classify `OUTAGE`,
  content-shaped faults `ANOMALY`, and the two never collide in the logged status.
- **Fallback safety:** whenever the status is not `HEALTHY` and a fallback exists,
  `GuardResult.prices` is the fallback, never the corrupted series, and `degraded` is
  true.
- **Schema invariant:** `fetch_day_ahead` output passes every `load_prices` check.

## Acceptance gate

*Blocks:* Release 1 ships. Every box must pass.

- [x] Parser and schema tests green **token-free**, on synthetic inputs, no network in
      CI.
- [x] Guard golden oracles green, including the anti-false-positive cases (2b, 2d, 5)
      and the resolution-change label (3b).
- [x] All property invariants hold across Hypothesis seeds.
- [x] Outage and anomaly are distinct in the structured log output, asserted in a test.
- [x] The band shift holds in two halves, split along what each can actually prove.
      **The mechanism, token-free in CI:** a synthetic calm series versus the same
      series with its daily cycle stretched; wider spread lifts the ceiling and each
      slice sits in its own band. **The real-world fact, token-gated:** real NL summer
      is genuinely more volatile than real Q1, and the band survives real prices. No
      real slice can be committed to parametrize the band, so that half is not
      available in CI and is not claimed there.
- [x] Live integration passes locally with token and CA bundle, and skips cleanly
      without them.
- [x] Backtest and example fetch path routes through `guarded_fetch`; shared provenance
      demonstrated end-to-end.
- [x] All other gates unchanged; `ruff`, `ruff format`, `lint-imports` (`data` still a
      leaf), and docs-lint clean.

The originally planned **cross-source** check is **dropped, not deferred**: it compared
a third-party slice that the no-committed-data decision removed from the repo. It
survives as the one-off feed-sanity probe recorded above, which is what it was worth.

## Out of scope

- **Intraday, imbalance, generation/load, and capacity markets.** Day-ahead only.
- **A general ENTSO-E client** for other document types; only A44, NL and BE.
- **Automatic CA-bundle discovery.** The operator sets the environment variables.
- **Multi-year pulls and cross-year band re-validation.** One window per fetch, and
  the band is re-validated per slice against that slice's own statistics.
- **Fetch inside the dispatch endpoint.** The endpoint's client-supplied-prices
  contract is unchanged; the guard wraps the offline and batch fetch path.
- **Retry and backoff tuning, and alerting transports.** The guard classifies and
  logs; wiring a real alert sink is ops config.
- **Forecast-drift monitoring.** A different signal: model decay, not feed corruption.
- **Imputation or auto-repair of a bad series.** The guard falls back to
  last-known-good; it never interpolates. Silent repair is itself a nightmare failure
  mode.
- **A general data-quality framework.** One focused module.

## Decisions

**Loader (reviewed 2026-06-26).**

1. **entsoe-py versus a hand-rolled parser.** **Resolved: entsoe-py**, whose parser is
   the token-free entry point the parser test targets. One dependency added.
2. **Volatile slice for the band check.** **Resolved: NL 2024 summer**, hourly, which
   isolates the seasonal shift from the 2025-10 15-minute switch.
3. **Committing a raw ENTSO-E XML sample.** **Resolved: no.** The parser test uses a
   synthetic A44 document.
4. **Cache location.** **Resolved:** `data/cache/*.parquet`, gitignored.
5. **How the cache gets switched on** (raised 2026-07-26, after the cache was found
   built but dormant): `cache_dir` was opt-in and *nothing opted in*, so every run
   re-pulled the same frozen history. **Resolved:** the loaders fall back to
   `$BESS_CACHE_DIR`, so a session opts in once rather than threading a path through
   every call site. An explicit argument still wins, and unset still means no cache, so
   CI is untouched. The live tests set it for themselves and the root conftest clears
   it everywhere else, so the suite never inherits a developer's cache.
   **The loader watchdog opts out** deliberately: it is the check on the live API and
   its schema, and a fetch served from parquet would re-assert that against a file this
   repo wrote earlier, passing indefinitely after ENTSO-E broke. The other live tests
   cache freely, since they consume real prices as *input* rather than testing the
   transport that produced them.
   No expiry, deliberately: a published day-ahead price is a settled auction result
   that is never revised, and the key pins the exact window, so a hit is correct by
   construction.

**Guard (reviewed 2026-07-01).**

6. **Stuck-feed threshold.** **Resolved:** express it in **wall-clock hours**,
   converted to a slot count per resolution, not a fixed slot count, so it survives the
   15-minute switch.
   **Revised on measurement (2026-07-15):** the original single 8-hour bound was
   wrong in both directions, as the evidence above shows. It became **two** bounds
   keyed on whether the repeated price is focal: `max_flat_hours = 4.0` for arbitrary
   values and `max_focal_flat_hours = 24.0` for focal ones.
7. **Sanity band.** **Resolved: `(-600, 5000)`**, grounded in the EPEX SDAC limits with
   one escalation step of headroom, verified against EPEX and ENTSO-E. Revalidate only
   if SDAC changes its limits.
8. **`GuardResult` home.** **Resolved: the `data` leaf**, a frozen dataclass *read* by
   consumers exactly as the serving layer reads a `Schedule`. No new import edge.
9. **Ship-gating.** **Resolved: the guard gates the Release-1 ship.** Shipping "done"
   and then bolting on a promised reliability piece is weaker than shipping once,
   complete.
