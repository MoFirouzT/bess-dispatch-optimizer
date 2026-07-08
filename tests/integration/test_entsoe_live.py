"""Integration — real-data sanity-band re-validation against live ENTSO-E.

Contract: docs/specs/R1.4b-entsoe-loader.md § "Golden / property expectations"
(real-data band) and § "Acceptance gate". This is the only place the project
touches the live API, and it is **token-gated**: skipped unless `ENTSOE_API_TOKEN`
is set (so it never runs in CI). Nothing fetched here is committed — the data is
pulled at runtime and discarded.

What it proves on *real* NL day-ahead prices:
  (a) the provable ordering `V_greedy <= V_roll <= V*` survives real volatility;
  (b) each slice's annualized ceiling sits in the §5 band derived from its *own*
      daily spread, and a volatile **summer** slice has a wider spread and higher
      ceiling than a calm **Q1** slice (the §5 band shifts up seasonally).

Network setup (this machine): a TLS-intercepting proxy means uv-Python needs the
Keychain roots — see docs/specs/R1.4b-entsoe-loader.md § "Environment note" and
.env.example. Without `REQUESTS_CA_BUNDLE`/`SSL_CERT_FILE` the live fetch fails
`CERTIFICATE_VERIFY_FAILED`; that is operator setup, not a code defect.
"""

import os

import pandas as pd
import pytest

from bess.assets.battery import BatterySpec
from bess.backtest.engine import run_backtest
from bess.data.entsoe import fetch_day_ahead

pytestmark = pytest.mark.integration

RED_FLAG_EUR_PER_MWH_YR = 50_000.0  # §5 leakage red flag (matches the synthetic gate D)

requires_token = pytest.mark.skipif(
    not os.environ.get("ENTSOE_API_TOKEN"),
    reason="ENTSOE_API_TOKEN not set — live ENTSO-E integration test skipped (never runs in CI)",
)


def _checked_report(prices: pd.Series):
    """Run the backtest, assert the provable ordering, return the report."""
    spec = BatterySpec()  # 1 MWh / 1 MW, η=0.95
    rep = run_backtest(prices, spec, dt=1.0, window="1D")
    assert rep.greedy.revenue_eur <= rep.rolling.revenue_eur + 1e-6
    assert rep.rolling.revenue_eur <= rep.perfect_foresight.revenue_eur + 1e-6
    assert rep.constraint_satisfaction
    return rep


def _assert_in_own_band(rep) -> None:
    """The annualized ceiling sits in the §5 band derived from the slice's *own*
    daily spread (docs/formulation.md § "Sanity band"), not an absolute constant.

    The 1-cycle/day mean-spread heuristic is a *lower* anchor; the perfect-foresight
    ceiling exceeds it because it exploits the best hours rather than the mean. On
    real NL hourly data that ratio is ~1.25 across both seasons — well inside [0.8,
    1.6]·heuristic. This is why a calm-calibrated absolute red flag (the synthetic
    gate D's €50k) is the wrong tool for an annualized volatile month: a genuinely
    volatile summer legitimately annualizes above it, but stays inside its own band.
    """
    spec = BatterySpec()
    # `ceiling` is already per MWh usable, so E_usable must NOT reappear here
    # (formulation §R1.4 sanity band: c = η_rt · cycles/day · 365).
    c = spec.eta_charge * spec.eta_discharge * 365.0
    heuristic = c * rep.mean_daily_spread_eur
    ceiling = rep.annualized_ceiling_per_mwh
    assert 0.8 * heuristic < ceiling < 1.6 * heuristic
    assert ceiling < RED_FLAG_EUR_PER_MWH_YR * 2  # absolute backstop against gross leakage


@requires_token
def test_real_data_seasonal_band_shift_and_ordering():
    # Calm: NL winter Q1 (hourly). Volatile: NL 2024 summer (hourly — isolates the
    # seasonal shift from the 2025-10 PT15M switch). Fetched live, never committed.
    calm = _checked_report(
        fetch_day_ahead(
            "NL", pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2024-02-01", tz="UTC")
        )
    )
    volatile = _checked_report(
        fetch_day_ahead(
            "NL", pd.Timestamp("2024-06-01", tz="UTC"), pd.Timestamp("2024-07-01", tz="UTC")
        )
    )

    # Each ceiling sits in the band derived from its own price statistics.
    _assert_in_own_band(calm)
    _assert_in_own_band(volatile)

    # Seasonal shift: the volatile summer slice has both a wider daily spread and a
    # higher annualized ceiling than calm winter — the §5 band shifts up.
    assert volatile.mean_daily_spread_eur > calm.mean_daily_spread_eur
    assert volatile.annualized_ceiling_per_mwh > calm.annualized_ceiling_per_mwh
