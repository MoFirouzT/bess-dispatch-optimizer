"""Integration — R2.5b tail dispatch value on real ENTSO-E NL prices.

Contract: docs/specs/R2.5b-tail-dispatch-value.md § "Acceptance gate". Token-gated
(skipped unless `ENTSOE_API_TOKEN` is set; deselected in CI); nothing fetched is
committed. Uses the R2.1c fundamentals loader for the conditional tail's covariate.

What it reports on *real* prices (the sign is a FINDING, not a gate, per the R2.5
forecast-value honesty rule): the per-window distribution of the tail value TV
(realized-euro value of the tail-informed commitment minus the plain-bootstrap
commitment) across a recourse-budget grid, so the ρ-dependence is visible. TV
gates the R2.2d go/no-go: a null (recourse already captures realized spikes, so the
day-ahead tail adds nothing) is a legitimate, informative result.

Network setup (this machine): a TLS-intercepting proxy means uv-Python may need the
Keychain roots — see docs/specs/R1.4b-entsoe-loader.md § "Environment note".
"""

import os

import numpy as np
import pytest

pd = pytest.importorskip("pandas")

from bess.assets.battery import BatterySpec  # noqa: E402
from bess.data.entsoe import fetch_day_ahead, fetch_fundamentals  # noqa: E402
from bess.stochastic.study import tail_value_across_windows  # noqa: E402

pytestmark = pytest.mark.integration

requires_token = pytest.mark.skipif(
    not os.environ.get("ENTSOE_API_TOKEN"),
    reason="ENTSOE_API_TOKEN not set — live ENTSO-E integration test skipped (never runs in CI)",
)

_BATT = BatterySpec(capacity=2.0, soc_initial=0.5, soc_terminal=0.5)
_RHOS = (0.25, 1.0)  # tight vs generous recourse; the ρ-dependence is the point


@requires_token
def test_tail_value_distribution_on_real_windows():
    import pandas as pd

    start = pd.Timestamp("2024-03-01", tz="UTC")
    end = pd.Timestamp("2024-06-01", tz="UTC")
    prices = fetch_day_ahead("NL", start, end)
    fund = fetch_fundamentals("NL", start, end).reindex(prices.index)
    residual_load = (fund["load_da"] - fund["wind_da"] - fund["solar_da"]).to_numpy()

    print("\nR2.5b tail dispatch value on real NL 2024 (Mar-Jun), conditional tail:")
    for rho in _RHOS:
        windows = tail_value_across_windows(
            prices,
            _BATT,
            residual_load=residual_load,
            history_days=28,
            n_scenarios=30,
            rho=rho,
            seed=0,
        )
        tv = np.array([w.tv_eur for w in windows])
        assert len(tv) >= 40
        # Bookkeeping holds for every window (the only hard invariant here).
        for w in windows:
            assert w.tv_eur == pytest.approx(w.profit_tail_eur - w.profit_plain_eur, abs=1e-6)
        print(
            f"  rho={rho:<4}: n={len(tv)}  median={np.median(tv):+.2f}  mean={tv.mean():+.2f}"
            f"  %pos={100 * np.mean(tv > 0):.0f}"
            f"  q25={np.percentile(tv, 25):+.2f} q75={np.percentile(tv, 75):+.2f}"
        )

    # Sign is a finding, not a gate (R2.5 rule). The only assertion is that the study
    # is well-formed and produced a distribution over enough real windows above.
