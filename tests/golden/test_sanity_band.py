"""Gate D — structural sanity band on a deterministic SYNTHETIC price series.

Contract: docs/specs/R1.4a-backtest.md § "Acceptance gate". Math/§5 band:
docs/formulation.md § "R1.4 — Backtest semantics".

No price data is committed to the repo (copyright-clean by construction — see
docs/specs/R1.4a-backtest.md § "Committed data"). This gate runs on a synthetic
series shaped like a calm NL day-ahead month (cheap nights, evening peak, gentle
midday, occasional solar dip). It still catches the dangerous bugs: broken
ordering, leakage-inflated magnitude, sign/efficiency errors. Validation against
*real* ENTSO-E statistics lives in the R1.4b token-gated integration test, not in
CI.
"""

from bess.assets.battery import BatterySpec
from bess.backtest.engine import run_backtest
from bess.data.fixtures import synthetic_day_ahead

# §5 leakage red flag: a 1-hour asset cannot exceed the perfect-foresight ceiling
# band; > ~€50k/MWh-yr means look-ahead leakage, not alpha.
RED_FLAG_EUR_PER_MWH_YR = 50_000.0


def test_structural_sanity_band_on_synthetic_series():
    prices = synthetic_day_ahead()
    spec = BatterySpec()  # 1 MWh / 1 MW, η=0.95
    rep = run_backtest(prices, spec, dt=1.0, window="1D")

    # Provable ordering holds on a realistic-shaped series.
    assert rep.greedy.revenue_eur <= rep.rolling.revenue_eur + 1e-6
    assert rep.rolling.revenue_eur <= rep.perfect_foresight.revenue_eur + 1e-6
    assert 0.0 <= rep.pct_of_perfect_foresight <= 1.0 + 1e-6
    assert rep.constraint_satisfaction

    # Coefficient recomputed from the spec (1 cycle/day heuristic) — not hard-coded.
    c = spec.eta_charge * spec.eta_discharge * spec.capacity * (1.0 - spec.soc_min) * 365.0
    heuristic = c * rep.mean_daily_spread_eur

    annualized = rep.annualized_ceiling_per_mwh
    # Lower bound: must capture most of one daily cycle (guards sign/efficiency bugs).
    assert annualized > 0.8 * heuristic
    # Upper bound: the §5 leakage red flag (guards look-ahead inflation).
    assert annualized < RED_FLAG_EUR_PER_MWH_YR
    # Spread is in a plausible day-ahead range.
    assert 30.0 < rep.mean_daily_spread_eur < 200.0
