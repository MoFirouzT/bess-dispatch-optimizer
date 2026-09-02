"""Integration — R2.6 bid-curve value on real ENTSO-E NL prices.

Contract: docs/specs/bid-curves.md § "Acceptance gate". Token-gated (skipped
unless `ENTSOE_API_TOKEN` is set; deselected in CI); nothing fetched is committed.

What it reports on *real* prices (the sign is a FINDING, not a gate, per the R2.5
forecast-value honesty rule): the per-window distribution of the bid-curve value
BCV, the realized euros of a price-contingent commitment minus a single blind one,
across a recourse-budget grid. The ρ-dependence is the point. The curve can only
buy what the recourse cannot already provide after the fact, so a null at generous
ρ is the expected shape and a null everywhere is a legitimate result.

Two numbers travel with every euro figure, and both are limitations rather than
footnotes. The **delivery gap** is the volume committed and not delivered, which
imbalance settlement would charge for (R3.1) and this study does not price. The
**scenario count** is 10 rather than the 30 the R2.5/R2.5b studies use, because the
curve program's monotonicity chain couples all commitment branches and its solve
cost grows steeply in S (spec R2.6, decision 4).

Network setup (this machine): a TLS-intercepting proxy means uv-Python may need the
Keychain roots — see docs/specs/data-feed.md § "Environment note".
"""

import os

import numpy as np
import pytest

pd = pytest.importorskip("pandas")

from bess.assets.battery import BatterySpec  # noqa: E402
from bess.data.entsoe import fetch_day_ahead  # noqa: E402
from bess.studies import bid_curve_value_across_windows  # noqa: E402

pytestmark = pytest.mark.integration

requires_token = pytest.mark.skipif(
    not os.environ.get("ENTSOE_API_TOKEN"),
    reason="ENTSOE_API_TOKEN not set — live ENTSO-E integration test skipped (never runs in CI)",
)

_BATT = BatterySpec(capacity=2.0, soc_initial=0.5, soc_terminal=0.5)
_RHOS = (0.25, 1.0)  # tight vs generous recourse; the ρ-dependence is the point
_N_SCENARIOS = 10  # see the module docstring: the curve program does not scale in S


@requires_token
def test_bid_curve_value_distribution_on_real_windows():
    import pandas as pd

    start = pd.Timestamp("2024-03-01", tz="UTC")
    end = pd.Timestamp("2024-05-01", tz="UTC")
    prices = fetch_day_ahead("NL", start, end)

    print("\nR2.6 bid-curve value on real NL 2024 (Mar-May):")
    for rho in _RHOS:
        windows = bid_curve_value_across_windows(
            prices, _BATT, history_days=28, n_scenarios=_N_SCENARIOS, rho=rho, seed=0
        )
        assert windows, f"no windows can be scored at rho={rho}"

        bcv = np.array([w.bcv_eur for w in windows])
        gap = np.array([w.delivery_gap_curve_mwh for w in windows])
        gap_scalar = np.array([w.delivery_gap_scalar_mwh for w in windows])
        print(
            f"  rho={rho}: n={len(bcv)} windows | BCV median {np.median(bcv):+.2f} "
            f"mean {bcv.mean():+.2f} EUR | {100 * (bcv > 0).mean():.0f}% positive | "
            f"quartiles [{np.percentile(bcv, 25):+.2f}, {np.percentile(bcv, 75):+.2f}] | "
            f"delivery gap median curve {np.median(gap):.2f} vs "
            f"scalar {np.median(gap_scalar):.2f} MWh"
        )

        # Bookkeeping only; the sign of BCV is reported, never asserted.
        for w in windows:
            assert w.bcv_eur == pytest.approx(w.profit_curve_eur - w.profit_scalar_eur, abs=1e-5)
            assert w.delivery_gap_curve_mwh >= -1e-9
