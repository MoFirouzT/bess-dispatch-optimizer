"""Integration — R2.9: is the tuned interval sharper than the shipped one?

Contract: docs/specs/interval-sharpness.md § "Acceptance gate".
Token-gated and `studies`-marked: the search fits 324 configurations, so it is
deselected from the routine live tier and run deliberately. Nothing fetched is
committed.

**Selection and reporting are separated on purpose.** The search runs on tuning
blocks placed in the gaps between the reporting blocks, which no gate scores; the winner
is then re-measured on R2.1d's frozen 52-fold reporting layout. The margin reported here
is therefore not the margin the winner was chosen on, and a configuration that only
transfers to its own tuning blocks shows up as a null rather than as an improvement.

**What this module asserts changed when the phase concluded, and the reason is recorded
here rather than only in the spec.** It was written to decide adoption, so it asserted
that the search's winner was no worse than the shipped model on coverage, per-hour
calibration and pinball skill. The R2.9 run answered that question with **no**: on NL the
winner's `max_hour_deviation` rises 0.065 to 0.070 (a narrower interval everywhere,
which fixes over-coverage at 21:00 and pushes 11:00 down to 0.830), and on BE pinball
skill at the lower edge worsens 0.192 to 0.196. The defaults were not changed.

Those assertions are gone **because there is no tuned model in the tree to gate**, not
because they were inconvenient. Their verdict is recorded in the spec's acceptance gate
as two boxes that stay unticked, with the measured numbers beside them. What survives
here is a gate on the model that actually ships: the incumbent must still meet its own
R2.1 coverage claim, and the search must still run reproducibly on disjoint folds. The
comparison is printed every run, so re-opening the question means reading the output, not
rebuilding the harness.

**The width change is reported with both of its widths and they are never combined**
(R2.8): a day-block bootstrap interval over test days, and the spread over
`random_state`. The second is **structurally zero** here and is not a stability result:
LightGBM runs with `deterministic=True`, `n_jobs=1` and no bagging or feature
subsampling, so the seed has no entry point into the fit. R2.8's rule was written for
scenario draw noise and does not transfer to the forecaster.
"""

import os

import numpy as np
import pytest
from span import span_prices

from bess.forecaster.evaluate import CoverageResult, _price_days, walk_forward_coverage
from bess.forecaster.tune import INCUMBENT, REPORTING_LAYOUT, search_sharpest, tuning_folds

pytestmark = [pytest.mark.integration, pytest.mark.studies]

requires_token = pytest.mark.skipif(
    not os.environ.get("ENTSOE_API_TOKEN"),
    reason="ENTSOE_API_TOKEN not set — live ENTSO-E integration test skipped (never runs in CI)",
)

pytest.importorskip("lightgbm")
pytest.importorskip("mapie")

#: The seeds the width spread is measured over (spec § Acceptance gate).
_SEEDS = (0, 1, 2)
_BAND = (0.85, 0.95)


def _report_on(prices, params, seed: int) -> CoverageResult:
    res = walk_forward_coverage(
        prices, return_detail=True, random_state=seed, **REPORTING_LAYOUT, **params
    )
    assert isinstance(res, CoverageResult)
    return res


def _overlaps(interval, band) -> bool:
    return interval[0] <= band[1] and band[0] <= interval[1]


@requires_token
@pytest.mark.parametrize("zone", ["NL", "BE"])
def test_sharpness_search_and_its_reporting_fold_margin(zone):
    """Run the search, re-measure both models on the reporting folds, report the margin.

    Asserts what must hold of the **shipped** model: its coverage interval still
    overlaps the R2.1 band on the reporting folds, and the fold layout still evaluates
    the days the layout promises. The tuned candidate's margin is **reported, not
    asserted**: there is no threshold a width reduction should pass, and picking one
    after seeing the number is not a gate. See the module docstring for what this test
    used to assert and why it no longer does.
    """
    prices = span_prices(zone)
    search = search_sharpest(prices, progress=True)

    print(
        f"\nR2.9 sharpness search ({zone}, {len(search.all_candidates)} configs, "
        f"gap-placed tuning folds):"
        f"\n  incumbent: width={search.incumbent.mean_width:.2f} "
        f"coverage={search.incumbent.coverage:.3f} "
        f"max_hour_dev={search.incumbent.max_hour_deviation:.3f}"
        f"\n  selected : {search.selected.params}"
        f"\n             width={search.selected.mean_width:.2f} "
        f"coverage={search.selected.coverage:.3f} "
        f"max_hour_dev={search.selected.max_hour_deviation:.3f}"
        f"\n  tuning-fold width reduction: {search.width_reduction:.2f} EUR/MWh"
        f"  (null={search.is_null})"
        f"\n  feasible: {len(search.ranked)}/{len(search.all_candidates) + 1}"
    )

    # Re-measure both models on the reporting folds, across seeds.
    inc = {s: _report_on(prices, INCUMBENT, s) for s in _SEEDS}
    sel = {s: _report_on(prices, dict(search.selected.params), s) for s in _SEEDS}
    inc0, sel0 = inc[0], sel[0]

    inc_widths = np.array([r.mean_width for r in inc.values()])
    sel_widths = np.array([r.mean_width for r in sel.values()])
    print(
        f"  reporting folds ({sel0.n_test_days} test days, seeds {list(_SEEDS)}):"
        f"\n    incumbent width {inc_widths.mean():.2f} "
        f"(seed spread {inc_widths.max() - inc_widths.min():.2f}), "
        f"coverage {inc0.coverage:.3f} CI=[{inc0.ci_low:.3f}, {inc0.ci_high:.3f}]"
        f"\n    selected  width {sel_widths.mean():.2f} "
        f"(seed spread {sel_widths.max() - sel_widths.min():.2f}), "
        f"coverage {sel0.coverage:.3f} CI=[{sel0.ci_low:.3f}, {sel0.ci_high:.3f}]"
        f"\n    width change {inc_widths.mean() - sel_widths.mean():+.2f} EUR/MWh"
        f"\n    max_hour_dev incumbent {inc0.max_hour_deviation:.3f} "
        f"selected {sel0.max_hour_deviation:.3f}"
    )

    verdict = (
        "sharper"
        if sel0.max_hour_deviation <= inc0.max_hour_deviation + 1e-9
        else "sharper but worse calibrated per hour, so not adoptable"
    )
    print(f"    verdict for the tuned candidate: {verdict}")

    # The shipped model is what this gate protects. R2.9 did not change it, so the
    # R2.1 claim it carries is the thing that must still hold on these folds.
    assert _overlaps((inc0.ci_low, inc0.ci_high), _BAND), (
        f"{zone}: the shipped model's coverage interval "
        f"[{inc0.ci_low:.3f}, {inc0.ci_high:.3f}] lies wholly outside {_BAND} on the "
        "reporting folds, so the R2.1 claim no longer holds on this span"
    )
    assert inc0.n_test_days >= 250, "fewer evaluated days than the reporting layout implies"
    assert sel0.n_test_days == inc0.n_test_days, (
        "the two models were scored on different day counts, so the printed margin "
        "compares two different measurements"
    )


@requires_token
def test_the_search_reproduces_bitwise_on_a_second_run():
    """Same span, same grid, same seed: the same ranking, or the recorded result is noise.

    Runs a small grid rather than all 324, because reproducibility is a property of the
    search, not of the grid's size, and the full sweep is already run above.
    """
    prices = span_prices("NL")
    folds = tuning_folds(_price_days(prices))[:3]
    grid = [
        {**INCUMBENT, "num_leaves": 15},
        {**INCUMBENT, "num_leaves": 63},
        {**INCUMBENT, "n_estimators": 400},
    ]

    first = search_sharpest(prices, grid=grid, folds=folds)
    second = search_sharpest(prices, grid=grid, folds=folds)

    assert first.ranked == second.ranked
    assert first.all_candidates == second.all_candidates
    assert first.selected.params == second.selected.params
