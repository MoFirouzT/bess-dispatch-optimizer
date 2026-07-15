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
# band; > ~€50k/MWh-yr means look-ahead leakage, not alpha. Calibrated on the *calm*
# series: a genuinely volatile month legitimately annualizes above it (see the
# volatility test below), so it is an absolute bound only where volatility is calm.
RED_FLAG_EUR_PER_MWH_YR = 50_000.0


def _report(prices, spec):
    """Backtest + the ordering assertions every band check rides on."""
    rep = run_backtest(prices, spec, dt=1.0, window="1D")
    assert rep.greedy.revenue_eur <= rep.rolling.revenue_eur + 1e-6
    assert rep.rolling.revenue_eur <= rep.perfect_foresight.revenue_eur + 1e-6
    assert rep.constraint_satisfaction
    return rep


def _heuristic(rep, spec):
    """The 1-cycle/day mean-spread anchor: c = η_rt · cycles/day · 365, recomputed
    from the spec, never hard-coded. `annualized` is already per MWh usable, so
    E_usable must NOT reappear here (formulation §R1.4 sanity band)."""
    return spec.eta_charge * spec.eta_discharge * 365.0 * rep.mean_daily_spread_eur


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
    # `annualized` is already per MWh usable, so E_usable must NOT reappear here
    # (formulation §R1.4 sanity band: c = η_rt · cycles/day · 365).
    c = spec.eta_charge * spec.eta_discharge * 365.0
    heuristic = c * rep.mean_daily_spread_eur

    annualized = rep.annualized_ceiling_per_mwh
    # Lower bound: must capture most of one daily cycle (guards sign/efficiency bugs).
    assert annualized > 0.8 * heuristic
    # Upper bound: the §5 leakage red flag (guards look-ahead inflation).
    assert annualized < RED_FLAG_EUR_PER_MWH_YR
    # Spread is in a plausible day-ahead range.
    assert 30.0 < rep.mean_daily_spread_eur < 200.0


def test_band_shifts_up_with_volatility():
    """The band tracks the series' own volatility: a wider daily spread lifts the
    ceiling, and each slice sits in the band derived from its *own* statistics.

    This is the token-free half of the seasonal-shift check. It gates the **engine's
    mechanism** (wider spread ⇒ proportionally higher ceiling, each inside its own
    band) across volatility regimes in CI, where no real volatile slice can be
    committed (ADR-0005). It does **not** prove the real-world claim that NL summer
    is more volatile than NL Q1 — that is a fact about the market, not the code, and
    stays in the token-gated `tests/integration/test_entsoe_live.py`.
    """
    spec = BatterySpec()  # 1 MWh / 1 MW, η=0.95
    calm_prices = synthetic_day_ahead()
    volatile_prices = synthetic_day_ahead(spread_scale=2.0)
    calm = _report(calm_prices, spec)
    volatile = _report(volatile_prices, spec)

    # Each ceiling sits in the band derived from its own spread. The 1-cycle/day
    # heuristic is a *lower* anchor; perfect foresight exceeds it by exploiting the
    # best hours rather than the mean, by ~1.2x in both regimes.
    for rep in (calm, volatile):
        heuristic = _heuristic(rep, spec)
        assert 0.8 * heuristic < rep.annualized_ceiling_per_mwh < 1.6 * heuristic

    # The shift itself: more volatility ⇒ wider spread ⇒ higher ceiling.
    assert volatile.mean_daily_spread_eur > calm.mean_daily_spread_eur
    assert volatile.annualized_ceiling_per_mwh > calm.annualized_ceiling_per_mwh

    # Stretching about the cycle's own mean changes amplitude, not level: the two
    # series share a mean *exactly* (identical noise draws, and the scaled deviation
    # sums to zero). Without this, the higher ceiling could be a price-level shift
    # rather than the volatility the test claims to vary. The daily spread itself is
    # deliberately not asserted to double: the per-hour noise and the solar dip are
    # not scaled, so it grows sub-linearly (71 → 135, not 142).
    assert volatile_prices.mean() == calm_prices.mean()
    assert volatile_prices.std() > 1.7 * calm_prices.std()

    # The calm-calibrated red flag does not apply here: the volatile ceiling
    # legitimately clears €50k/MWh-yr while staying inside its own band. Only gross
    # leakage (an order of magnitude) is caught absolutely.
    assert volatile.annualized_ceiling_per_mwh > RED_FLAG_EUR_PER_MWH_YR
    assert volatile.annualized_ceiling_per_mwh < 2.0 * RED_FLAG_EUR_PER_MWH_YR
