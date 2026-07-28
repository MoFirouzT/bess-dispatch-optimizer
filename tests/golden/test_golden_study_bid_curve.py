"""Golden oracles for the R2.6 bid-curve value study (formulation-r2 §R2.6, evaluation).

Two things are pinned here, both exactly:

- **The curve read.** ``curve_response`` resolves a submitted step function at a
  realized price: the quantity of the last step whose price the realization
  reaches, with the lowest step extended downward. Hand-checked at every boundary,
  because a wrong read silently mis-scores every window in the study.
- **The scoring.** A commitment is scored as a *cash-flow obligation*: it enters
  only the recourse budget and the recourse dispatch carries the physics. Where the
  §R2.5 scoring path also applies (an R1.1-feasible commitment), the two agree
  exactly, which is what makes the curve-versus-scalar comparison fair. The
  bid-curve value is null on a degenerate set and positive on a designed one.

The designed asset is the R2.6 golden asset: 2 MWh / 1 MW at eta = 1 with
e_0 = e_tgt = 1 MWh over T = 2, so every feasible dispatch is ``g = [a, -a]``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bess.assets.battery import BatterySpec
from bess.scenarios import ScenarioSet
from bess.stochastic import curve_response, solve_stochastic
from bess.studies import bid_curve_value_from_sets

TOL = 1e-6

_BATT = BatterySpec(
    capacity=2.0,
    soc_min=0.0,
    soc_initial=0.5,
    soc_terminal=0.5,
    eta_charge=1.0,
    eta_discharge=1.0,
)


def _scen(paths: list[list[float]], probs: list[float]) -> ScenarioSet:
    arr = np.asarray(paths, dtype=float)
    idx = pd.date_range("2026-01-01", periods=arr.shape[1], freq="h", tz="UTC")
    return ScenarioSet(paths=arr, probs=np.asarray(probs, dtype=float), index=idx)


# ------------------------------------------------------------- the curve read


def test_curve_response_reads_the_step_function_by_hand() -> None:
    """One hour, three steps: below the lowest, on a step, between steps, above all."""
    curve = [[(10.0, -1.0), (50.0, 0.0), (90.0, 1.0)]]

    assert curve_response(curve, [5.0]) == [-1.0]  # below the lowest step
    assert curve_response(curve, [10.0]) == [-1.0]  # exactly on a step edge
    assert curve_response(curve, [49.99]) == [-1.0]  # still on the first step
    assert curve_response(curve, [50.0]) == [0.0]  # the next edge
    assert curve_response(curve, [89.99]) == [0.0]
    assert curve_response(curve, [1e6]) == [1.0]  # above every step


def test_curve_response_reproduces_a_branch_on_its_own_path() -> None:
    """Feed scenario s's prices back in and the curve returns scenario s's branch.

    The measurability condition says the commitment is a function of that hour's
    price, so reading the curve at the prices it was built from must return exactly
    what the program committed in that state. This is the tie between the optimizer
    output and the scoring input; if it fails, every scored euro is misattributed.
    """
    scen = _scen([[10.0, 90.0], [90.0, 10.0]], [0.5, 0.5])
    res = solve_stochastic(scen, _BATT, rho=0.0, bid_curve=True)
    assert res.curve is not None and res.g_da_branches is not None

    for s, path in enumerate(scen.paths):
        assert curve_response(res.curve, path) == pytest.approx(res.g_da_branches[s], abs=TOL)


# --------------------------------------------------------------- the scoring


def test_obligation_scoring_agrees_with_schedule_scoring_where_both_apply() -> None:
    """An R1.1-feasible commitment scores identically under both evaluation paths.

    §R2.5 pins the commitment into an evaluation solve (imposing its physics); §R2.6
    passes it as a numeric obligation into the budget alone. For a commitment that
    *is* a schedule the two programs have the same feasible set and objective, so
    they must agree exactly. This is what keeps the curve-vs-scalar comparison fair.
    """
    realized = [10.0, 90.0]
    evaluation = _scen([realized], [1.0])
    commitment = [-1.0, 1.0]  # charge then discharge: R1.1-feasible on this asset

    obligation = solve_stochastic(evaluation, _BATT, rho=0.5, commitment=commitment)
    schedule = solve_stochastic(
        evaluation,
        _BATT,
        rho=0.5,
        fix_da=([1.0, 0.0], [0.0, 1.0]),
        pi_da=realized,
    )
    assert obligation.expected_profit == pytest.approx(schedule.expected_profit, abs=TOL)
    assert obligation.g_da == pytest.approx(commitment, abs=TOL)


def test_bid_curve_value_is_null_when_the_scenarios_are_identical() -> None:
    """No uncertainty, no curve: ties force one branch, so the value is exactly 0.

    Every scenario prices every hour the same, so the tie family collapses the curve
    to a single step per hour and the two commitments coincide. A non-zero value here
    would mean the study is measuring solver noise rather than contingency.
    """
    path = [10.0, 90.0, 20.0, 40.0]
    scen = _scen([path, path, path], [1 / 3, 1 / 3, 1 / 3])

    res = bid_curve_value_from_sets(scen, path, _BATT, rho=0.5)

    assert res.bcv_eur == pytest.approx(0.0, abs=TOL)
    assert res.profit_curve_eur == pytest.approx(res.profit_scalar_eur, abs=TOL)
    assert res.delivery_gap_curve_mwh == pytest.approx(res.delivery_gap_scalar_mwh, abs=TOL)


def test_bid_curve_value_is_positive_on_the_designed_instance() -> None:
    """The oracle-2 instance, scored on a realized path that is one of its states.

    Training states are [10,90] and [90,10]; the realized day turns out to be the
    first. The curve committed [-1,+1] for that state and earns the full 80; the
    scalar commitment had to pick one blind schedule against flat mean prices, and
    at rho=0 it cannot recover. The gap is the bid-curve value.
    """
    realized = [10.0, 90.0]
    scen = _scen([realized, [90.0, 10.0]], [0.5, 0.5])

    res = bid_curve_value_from_sets(scen, realized, _BATT, rho=0.0)

    assert res.profit_curve_eur == pytest.approx(80.0, abs=TOL)
    assert res.bcv_eur > 1e-3
    # On-support: the curve's realized commitment is a branch, so it is deliverable
    # and the recourse matches it exactly at rho = 0.
    assert res.delivery_gap_curve_mwh == pytest.approx(0.0, abs=TOL)
