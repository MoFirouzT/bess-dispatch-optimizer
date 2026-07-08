"""Golden oracles for scenario reduction (R2.2).

Unlike the forecaster's coverage gate, reduction on a tiny fixed set has an exact
answer, so R2.2 gets a hand-computable golden oracle, not only a statistical band.

Oracle 1 (fast forward selection, ell=1, hand-computed):
    3 one-period scenarios, values [0, 1, 10], probs [0.4, 0.4, 0.2], reduce to 2.
    Forward selection grows the kept set:
      step 1 pick the atom minimizing sum_i p_i * |x_i - x_u|:
        u=0 -> 0.4*1 + 0.2*10 = 2.4 ; u=1 -> 0.4*1 + 0.2*9 = 2.2 ; u=10 -> 7.6
        => keep the value-1 atom.
      step 2 add the atom minimizing the new nearest-kept cost:
        add 0  -> deleted {10}: 0.2*9 = 1.8 ; add 10 -> deleted {0}: 0.4*1 = 0.4
        => keep the value-10 atom.
    Deleted = {value 0}; its mass 0.4 redistributes to its nearest kept (value 1).
      kept values {1, 10}, probs {0.8, 0.2}, distance D = 0.4*1 = 0.4.

Oracle 2: reducing to the full size is the identity (distance 0).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bess.scenarios import ScenarioSet, reduce_scenarios

TOL = 1e-9


def _one_period_set() -> ScenarioSet:
    idx = pd.date_range("2026-01-01", periods=1, freq="h", tz="UTC")
    return ScenarioSet(
        paths=np.array([[0.0], [1.0], [10.0]]),
        probs=np.array([0.4, 0.4, 0.2]),
        index=idx,
    )


def test_oracle1_forward_selection_reduction() -> None:
    scen = _one_period_set()
    reduced, distance = reduce_scenarios(scen, n_reduced=2, method="forward", p=1)

    assert distance == 0.0 or abs(distance - 0.4) < TOL
    assert abs(distance - 0.4) < TOL

    kept = {float(v): float(p) for v, p in zip(reduced.paths[:, 0], reduced.probs, strict=True)}
    assert set(kept) == {1.0, 10.0}
    assert abs(kept[1.0] - 0.8) < TOL
    assert abs(kept[10.0] - 0.2) < TOL
    assert abs(reduced.probs.sum() - 1.0) < TOL


def test_oracle2_reduce_to_full_size_is_identity() -> None:
    scen = _one_period_set()
    reduced, distance = reduce_scenarios(scen, n_reduced=scen.n_scenarios, method="forward", p=1)

    assert abs(distance) < TOL
    assert reduced.n_scenarios == scen.n_scenarios
    np.testing.assert_allclose(np.sort(reduced.paths[:, 0]), np.sort(scen.paths[:, 0]), atol=TOL)
    assert abs(reduced.probs.sum() - 1.0) < TOL
