"""Integration — R2.1c exogenous fundamentals on real ENTSO-E NL, walk-forward.

Contract: docs/specs/R2.1c-exogenous-fundamentals.md § "Acceptance gate". Uses the
exact R2.1 walk-forward evaluation (fit strictly before each test block, pool
coverage), now threading the day-ahead residual-load features, on *real* data the
model did not calibrate on:

- **Coverage preserved (hard):** empirical coverage with fundamentals stays in the
  R2.1 band (0.9 ± 0.05). Fundamentals must not break calibration.
- **Accuracy no worse (honest, reported not asserted-positive):** walk-forward
  pinball skill with fundamentals is not materially worse than the price+calendar
  model, and the delta is printed with provenance. Per the R2.5 rule a null is
  reported, not suppressed; only gross breakage (misaligned/garbage features) trips
  the guard.

Doubly gated: needs the `forecast` dependency group AND a token; never runs in CI,
nothing fetched is committed. Run locally:
`uv run --group forecast pytest tests/integration/test_fundamentals_live.py -s`.
"""

import os

import pytest

pytest.importorskip("lightgbm")
pytest.importorskip("mapie")

import pandas as pd  # noqa: E402

from bess.data.entsoe import fetch_day_ahead, fetch_fundamentals  # noqa: E402
from bess.forecaster import walk_forward_coverage  # noqa: E402
from bess.forecaster.evaluate import walk_forward_pinball_skill  # noqa: E402

pytestmark = pytest.mark.integration

requires_token = pytest.mark.skipif(
    not os.environ.get("ENTSOE_API_TOKEN"),
    reason="ENTSOE_API_TOKEN not set — live ENTSO-E integration test skipped (never runs in CI)",
)

_FAST = dict(n_estimators=120, random_state=0)
_WF = dict(confidence_level=0.9, method="cqr", n_folds=3, test_days=5)


@requires_token
def test_fundamentals_preserve_coverage_and_do_not_hurt_accuracy():
    start = pd.Timestamp("2024-02-01", tz="UTC")
    end = pd.Timestamp("2024-06-01", tz="UTC")
    prices = fetch_day_ahead("NL", start, end)
    fund = fetch_fundamentals("NL", start, end)

    cov_base, _ = walk_forward_coverage(prices, **_WF, **_FAST)
    cov_fund, _ = walk_forward_coverage(prices, fundamentals=fund, **_WF, **_FAST)

    skill_base = walk_forward_pinball_skill(prices, **_WF, **_FAST)
    skill_fund = walk_forward_pinball_skill(prices, fundamentals=fund, **_WF, **_FAST)

    # Average pinball across the two interval edges (the walk-forward accuracy axis).
    pb_base = 0.5 * (skill_base.conformal_lower + skill_base.conformal_upper)
    pb_fund = 0.5 * (skill_fund.conformal_lower + skill_fund.conformal_upper)

    pct = 100 * (pb_fund - pb_base) / pb_base
    print(
        f"\nR2.1c live (NL 2024, walk-forward 3×5d out-of-sample):"
        f"\n  price+calendar : coverage={cov_base:.3f}  pinball={pb_base:.3f}"
        f"\n  +fundamentals  : coverage={cov_fund:.3f}  pinball={pb_fund:.3f}"
        f"\n  pinball delta  : {pb_fund - pb_base:+.3f} ({pct:+.1f}%)"
    )

    # Hard: fundamentals must not break calibration.
    assert 0.85 <= cov_fund <= 0.95, f"+fundamentals coverage {cov_fund:.3f} outside [0.85, 0.95]"
    # Honest guard: not materially worse (catches misalignment/garbage, not a null).
    assert pb_fund <= pb_base * 1.25, (
        f"+fundamentals pinball {pb_fund:.3f} materially worse than base {pb_base:.3f} "
        "(likely a feature-alignment defect, not a benign null)"
    )
