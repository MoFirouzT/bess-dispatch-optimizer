"""Property invariants for R2.6: price-contingent bid curves (formulation-r2 §R2.6).

Structural guarantees the delta promises for *any* scenario set:

- ``bid_curve=False`` is the R2.3 program, untouched (the opt-in rule);
- at ``lambda_=0`` the curve's objective is never below the scalar commitment's,
  because the curve's feasible set contains it and the two maximize the same
  expectation (the provable bound, §R2.6);
- the submitted curve is nondecreasing in price within every hour, and prices the
  auction cannot tell apart receive the same quantity;
- every commitment branch is physically deliverable on its own, and every
  scenario's recourse stays within the budget of *its* branch;
- scale invariance and determinism, as everywhere else in the repo.

MILP solves are not cheap, so these run over a small fixed set of seeds rather
than a Hypothesis sweep, matching ``test_stochastic.py``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bess.assets.battery import BatterySpec
from bess.scenarios import ScenarioSet
from bess.stochastic import solve_stochastic

TOL = 1e-6
TICK = 0.01  # market tick; ties are equality at this resolution (spec decision 3)

_BATT = BatterySpec(
    capacity=2.0,
    soc_min=0.0,
    soc_initial=0.5,
    soc_terminal=0.5,
    eta_charge=0.9,
    eta_discharge=0.9,
)


def _scen(paths: np.ndarray, probs: np.ndarray) -> ScenarioSet:
    arr = np.asarray(paths, dtype=float)
    idx = pd.date_range("2026-01-01", periods=arr.shape[1], freq="h", tz="UTC")
    return ScenarioSet(paths=arr, probs=np.asarray(probs, dtype=float), index=idx)


def _rand_set(seed: int, s: int = 3, t: int = 3) -> ScenarioSet:
    rng = np.random.default_rng(seed)
    raw = rng.random(s) + 0.05
    return _scen(rng.uniform(0.0, 60.0, size=(s, t)), raw / raw.sum())


def _soc_path(g: list[float], batt: BatterySpec, dt: float = 1.0) -> list[float]:
    """Re-derive the SoC trajectory of a net-export schedule (grid-side, R1.1 (1))."""
    e = batt.soc_initial * batt.capacity
    out = []
    for gt in g:
        charge, discharge = max(0.0, -gt), max(0.0, gt)
        e += batt.eta_charge * charge * dt - discharge / batt.eta_discharge * dt
        out.append(e)
    return out


# --------------------------------------------------------------- opt-in identity


@pytest.mark.parametrize("seed", range(3))
def test_default_path_is_the_r23_program(seed: int) -> None:
    scen = _rand_set(seed)
    default = solve_stochastic(scen, _BATT, rho=0.4)
    explicit = solve_stochastic(scen, _BATT, rho=0.4, bid_curve=False)

    assert explicit.objective == pytest.approx(default.objective, abs=TOL)
    assert explicit.g_da == pytest.approx(default.g_da, abs=TOL)
    assert explicit.curve is None
    assert explicit.g_da_branches is None


# ---------------------------------------------------------------- provable bound


@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("rho", [0.0, 0.4])
def test_curve_never_below_the_scalar_commitment(seed: int, rho: float) -> None:
    """The scalar solution is feasible for the curve program, at the same value."""
    scen = _rand_set(seed)
    scalar = solve_stochastic(scen, _BATT, rho=rho, lambda_=0.0, bid_curve=False)
    curve = solve_stochastic(scen, _BATT, rho=rho, lambda_=0.0, bid_curve=True)
    assert curve.objective >= scalar.objective - TOL


# ------------------------------------------------------------- the curve is legal


@pytest.mark.parametrize("seed", range(5))
def test_curve_is_nondecreasing_in_price_within_every_hour(seed: int) -> None:
    scen = _rand_set(seed)
    res = solve_stochastic(scen, _BATT, rho=0.4, bid_curve=True)
    assert res.curve is not None
    for hour in res.curve:
        prices = [p for p, _ in hour]
        quantities = [q for _, q in hour]
        assert prices == sorted(prices)
        assert all(b >= a - TOL for a, b in zip(quantities, quantities[1:], strict=False))


@pytest.mark.parametrize("seed", range(3))
def test_prices_the_auction_cannot_distinguish_get_the_same_quantity(seed: int) -> None:
    """Duplicate one scenario's prices at a single hour; the branches must agree there."""
    rng = np.random.default_rng(seed)
    paths = rng.uniform(0.0, 60.0, size=(3, 3))
    paths[1, 1] = paths[0, 1]  # a tie at hour 1, the rest of the paths still differ
    scen = _scen(paths, np.full(3, 1 / 3))

    res = solve_stochastic(scen, _BATT, rho=0.4, bid_curve=True)
    assert res.g_da_branches is not None
    assert res.g_da_branches[0][1] == pytest.approx(res.g_da_branches[1][1], abs=TOL)

    # A tie is one curve step, not two.
    assert res.curve is not None
    assert len({round(p / TICK) for p, _ in res.curve[1]}) == len(res.curve[1])


# ------------------------------------------------- every branch is deliverable


@pytest.mark.parametrize("seed", range(5))
def test_every_commitment_branch_is_physically_feasible(seed: int) -> None:
    """Whichever branch clears must be deliverable, so each obeys R1.1 on its own."""
    scen = _rand_set(seed)
    res = solve_stochastic(scen, _BATT, rho=0.4, bid_curve=True)
    assert res.g_da_branches is not None

    e_min = _BATT.soc_min * _BATT.capacity
    e_max = _BATT.capacity
    e_terminal = _BATT.soc_terminal * _BATT.capacity
    cap = max(_BATT.p_charge_max, _BATT.p_discharge_max)

    for branch in res.g_da_branches:
        assert all(abs(gt) <= cap + TOL for gt in branch)
        soc = _soc_path(branch, _BATT)
        assert all(e_min - TOL <= e <= e_max + TOL for e in soc)
        assert soc[-1] == pytest.approx(e_terminal, abs=1e-5)


@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("rho", [0.0, 0.3])
def test_recourse_stays_within_the_budget_of_its_own_branch(seed: int, rho: float) -> None:
    scen = _rand_set(seed)
    res = solve_stochastic(scen, _BATT, rho=rho, bid_curve=True)
    assert res.g_da_branches is not None
    budget = rho * max(_BATT.p_charge_max, _BATT.p_discharge_max)

    for branch, realized in zip(res.g_da_branches, res.recourse, strict=True):
        for committed, actual in zip(branch, realized, strict=True):
            assert abs(actual - committed) <= budget + 1e-5


# --------------------------------------------------------- scale and determinism


@pytest.mark.parametrize("k", [0.5, 4.0])
def test_scale_invariance(k: float) -> None:
    """Scaling the asset scales the objective by exactly k (ADR-0009, per-unit SoC)."""
    scen = _rand_set(0)
    big = _BATT.model_copy(
        update={
            "capacity": _BATT.capacity * k,
            "p_charge_max": _BATT.p_charge_max * k,
            "p_discharge_max": _BATT.p_discharge_max * k,
        }
    )
    base = solve_stochastic(scen, _BATT, rho=0.4, bid_curve=True)
    scaled = solve_stochastic(scen, big, rho=0.4, bid_curve=True)
    assert scaled.objective == pytest.approx(k * base.objective, abs=1e-5, rel=1e-6)


def test_determinism() -> None:
    scen = _rand_set(1)
    first = solve_stochastic(scen, _BATT, rho=0.4, bid_curve=True)
    second = solve_stochastic(scen, _BATT, rho=0.4, bid_curve=True)
    assert first.objective == pytest.approx(second.objective, abs=TOL)
    assert first.g_da_branches == second.g_da_branches
    assert first.curve == second.curve
