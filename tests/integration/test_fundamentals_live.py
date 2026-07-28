"""Integration — R2.1c exogenous fundamentals on real ENTSO-E NL, walk-forward.

Contract: docs/specs/price-forecaster.md § "Acceptance gate". Uses the
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

#: R2.1d: the shipped model capacity (no override), the 2021-2025 span, and folds
#: spread across it. The original numbers here came from three contiguous folds inside
#: one fortnight of May 2024, so the reported minus 16.6 percent pinball gain was a
#: fortnight statement; this re-measures it across seasons and regimes.
_SEED = dict(random_state=0)
_WF = dict(
    confidence_level=0.9,
    method="cqr",
    n_folds=52,
    test_days=5,
    train_days=365,
    spacing="even",
)
_SPAN = (pd.Timestamp("2021-01-01", tz="UTC"), pd.Timestamp("2025-09-30", tz="UTC"))


@requires_token
def test_fundamentals_preserve_coverage_and_do_not_hurt_accuracy():
    start, end = _SPAN
    prices = fetch_day_ahead("NL", start, end)
    fund = fetch_fundamentals("NL", start, end)

    res_base = walk_forward_coverage(prices, return_detail=True, **_WF, **_SEED)
    res_fund = walk_forward_coverage(prices, fundamentals=fund, return_detail=True, **_WF, **_SEED)

    skill_base = walk_forward_pinball_skill(prices, **_WF, **_SEED)
    skill_fund = walk_forward_pinball_skill(prices, fundamentals=fund, **_WF, **_SEED)

    # Average pinball across the two interval edges (the walk-forward accuracy axis).
    pb_base = 0.5 * (skill_base.conformal_lower + skill_base.conformal_upper)
    pb_fund = 0.5 * (skill_fund.conformal_lower + skill_fund.conformal_upper)

    pct = 100 * (pb_fund - pb_base) / pb_base
    print(
        f"\nR2.1c live, re-measured under R2.1d (NL 2021-2025, "
        f"{res_base.n_test_days} out-of-sample test days):"
        f"\n  price+calendar : coverage={res_base.coverage:.3f} "
        f"CI=[{res_base.ci_low:.3f}, {res_base.ci_high:.3f}]  pinball={pb_base:.3f}"
        f"\n  +fundamentals  : coverage={res_fund.coverage:.3f} "
        f"CI=[{res_fund.ci_low:.3f}, {res_fund.ci_high:.3f}]  pinball={pb_fund:.3f}"
        f"\n  pinball delta  : {pb_fund - pb_base:+.3f} ({pct:+.1f}%)"
    )

    # Hard: fundamentals must not break calibration. Interval-based, per R2.1d.
    assert res_fund.ci_low <= 0.95 and res_fund.ci_high >= 0.85, (
        f"+fundamentals coverage interval [{res_fund.ci_low:.3f}, {res_fund.ci_high:.3f}] "
        f"lies wholly outside [0.85, 0.95] (point estimate {res_fund.coverage:.3f})"
    )
    # Honest guard: not materially worse (catches misalignment/garbage, not a null).
    # Per the R2.5 rule a null or a shrunken effect is reported, never suppressed.
    assert pb_fund <= pb_base * 1.25, (
        f"+fundamentals pinball {pb_fund:.3f} materially worse than base {pb_base:.3f} "
        "(likely a feature-alignment defect, not a benign null)"
    )
