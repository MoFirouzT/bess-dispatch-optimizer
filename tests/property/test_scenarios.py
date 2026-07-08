"""Property invariants for scenario generation + reduction (R2.2).

Pure numpy/pandas; runs in the main CI job (no forecast group needed for the
forward-selection path). The k-means baseline is exercised separately, guarded.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bess.scenarios import ScenarioSet, generate_scenarios, kantorovich_distance, reduce_scenarios

TOL = 1e-9


class _FakeForecast:
    """Minimal stand-in exposing the one attribute the generator reads."""

    def __init__(self, point: np.ndarray, index: pd.DatetimeIndex) -> None:
        self.point = pd.Series(point, index=index, name="point")


def _random_set(rng: np.random.Generator, s: int, t: int) -> ScenarioSet:
    idx = pd.date_range("2026-01-01", periods=t, freq="h", tz="UTC")
    paths = rng.normal(50.0, 20.0, size=(s, t))
    raw = rng.random(s) + 0.05
    return ScenarioSet(paths=paths, probs=raw / raw.sum(), index=idx)


# ---------------------------------------------------------------- generation


@settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow])
@given(
    t=st.integers(min_value=1, max_value=6),
    m=st.integers(min_value=3, max_value=20),
    n=st.integers(min_value=1, max_value=200),
    seed=st.integers(min_value=0, max_value=10_000),
)
def test_generation_valid_measure_and_shape(t: int, m: int, n: int, seed: int) -> None:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=t, freq="h", tz="UTC")
    point = rng.normal(40.0, 10.0, size=t)
    residuals = rng.normal(0.0, 5.0, size=(m, t))

    scen = generate_scenarios(_FakeForecast(point, idx), residuals, n=n, seed=seed)

    assert scen.paths.shape == (n, t)
    assert scen.probs.shape == (n,)
    assert (scen.probs >= 0).all()
    assert abs(scen.probs.sum() - 1.0) < TOL
    np.testing.assert_allclose(scen.probs, 1.0 / n)


def test_generation_is_deterministic_and_bootstraps_residuals() -> None:
    idx = pd.date_range("2026-01-01", periods=4, freq="h", tz="UTC")
    point = np.array([10.0, 20.0, 30.0, 40.0])
    residuals = np.array([[1.0, 1.0, 1.0, 1.0], [-2.0, 0.0, 2.0, 4.0], [0.0, 0.0, 0.0, 0.0]])
    fc = _FakeForecast(point, idx)

    a = generate_scenarios(fc, residuals, n=500, seed=7)
    b = generate_scenarios(fc, residuals, n=500, seed=7)
    np.testing.assert_array_equal(a.paths, b.paths)

    # Bootstrap of whole rows: the sample mean path approaches point + mean(residual).
    expected = point + residuals.mean(axis=0)
    np.testing.assert_allclose(a.paths.mean(axis=0), expected, atol=1.5)

    # Every generated path equals point + one of the residual rows (whole-vector resample).
    for path in a.paths:
        assert np.isclose(path - point, residuals).all(axis=1).any()


# ----------------------------------------------------------------- reduction


@settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow])
@given(
    s=st.integers(min_value=4, max_value=12),
    t=st.integers(min_value=1, max_value=5),
    seed=st.integers(min_value=0, max_value=10_000),
    p=st.sampled_from([1, 2]),
)
def test_reduction_conserves_mass_and_keeps_original_atoms(
    s: int, t: int, seed: int, p: int
) -> None:
    rng = np.random.default_rng(seed)
    scen = _random_set(rng, s, t)
    k = max(2, s // 2)

    reduced, distance = reduce_scenarios(scen, n_reduced=k, method="forward", p=p)

    # valid measure, right size, mass conserved
    assert reduced.n_scenarios == k
    assert (reduced.probs >= 0).all()
    assert abs(reduced.probs.sum() - 1.0) < TOL

    # kept atoms are original atoms (real price paths, not synthetic centroids)
    for row in reduced.paths:
        assert np.isclose(scen.paths, row).all(axis=1).any()

    # the reported distance matches the public metric on the reduced support
    assert abs(distance - kantorovich_distance(scen, reduced, p=p)) < 1e-9


def test_forward_selection_beats_random_in_aggregate() -> None:
    """The reducer does real work: at a realistic reduction ratio it beats random
    subsetting on the large majority of instances and in the mean.

    Stated as an *aggregate statistical* claim, not a per-instance one: greedy
    forward selection is a heuristic (notably weak at k=2, where the central
    first medoid is a poor anchor), so a single tiny instance can sit above the
    random mean. At realistic scale (60 -> 15) that heuristic gap closes.
    """
    for p in (1, 2):
        wins, fwd_total, rnd_total = 0, 0.0, 0.0
        n_instances = 40
        for seed in range(n_instances):
            rng = np.random.default_rng(seed)
            scen = _random_set(rng, s=60, t=24)
            _, fwd = reduce_scenarios(scen, n_reduced=15, method="forward", p=p)

            rand_dists = [
                kantorovich_distance(
                    scen,
                    ScenarioSet(
                        scen.paths[rng.choice(60, size=15, replace=False)],
                        np.full(15, 1.0 / 15),
                        scen.index,
                    ),
                    p=p,
                )
                for _ in range(20)
            ]
            mean_rand = float(np.mean(rand_dists))
            wins += fwd <= mean_rand
            fwd_total += fwd
            rnd_total += mean_rand

        assert wins >= int(0.9 * n_instances), f"p={p}: forward won only {wins}/{n_instances}"
        assert fwd_total < rnd_total, f"p={p}: forward mean not below random mean"


@settings(max_examples=25, suppress_health_check=[HealthCheck.too_slow])
@given(
    s=st.integers(min_value=5, max_value=12),
    t=st.integers(min_value=1, max_value=4),
    seed=st.integers(min_value=0, max_value=10_000),
    p=st.sampled_from([1, 2]),
)
def test_distance_monotone_non_increasing_in_kept_count(s: int, t: int, seed: int, p: int) -> None:
    rng = np.random.default_rng(seed)
    scen = _random_set(rng, s, t)

    prev = np.inf
    for k in range(2, s + 1):
        _, distance = reduce_scenarios(scen, n_reduced=k, method="forward", p=p)
        assert distance <= prev + 1e-9
        prev = distance
    assert abs(prev) < TOL  # k == s is the identity, distance 0


def test_kmeans_baseline_runs_if_available() -> None:
    pytest.importorskip("sklearn")
    rng = np.random.default_rng(3)
    scen = _random_set(rng, 20, 4)

    reduced, distance = reduce_scenarios(scen, n_reduced=5, method="kmeans", p=2, seed=0)
    assert reduced.n_scenarios == 5
    assert abs(reduced.probs.sum() - 1.0) < TOL
    assert distance >= 0.0
