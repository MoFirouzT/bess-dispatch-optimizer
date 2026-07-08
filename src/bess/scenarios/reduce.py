"""Scenario reduction: Heitsch-Römisch fast forward selection + k-means baseline (R2.2).

See ``docs/formulation.md`` § R2.2 and ADR-0018. Forward selection greedily
grows the kept set to minimize the Kantorovich distance to the original, then
redistributes each deleted atom's mass to its nearest kept atom (keeping the
reduced measure a valid probability distribution over *original* paths). k-means
is the pragmatic baseline (centroids as representatives, cluster mass as
probability), imported lazily so the primary path needs no optional group.
"""

from __future__ import annotations

import numpy as np

from bess.scenarios.generate import ScenarioSet
from bess.scenarios.metrics import _ground_dist


def _forward_select(cost: np.ndarray, probs: np.ndarray, k: int) -> tuple[list[int], np.ndarray]:
    """Greedy fast forward selection.

    ``cost[i, j] = ‖π_i − π_j‖^p``. Returns the kept indices (in selection order)
    and, per atom, its minimum cost to the kept set (0 for kept atoms).
    """
    s = len(probs)
    kept: list[int] = []
    remaining = list(range(s))
    best = np.full(s, np.inf)  # min cost to the current kept set, per atom
    for _ in range(k):
        cand = np.array(remaining)
        # Cost if each candidate were added: min(best, cost[:, cand]) summed over mass.
        new_best = np.minimum(best[:, None], cost[:, cand])
        vals = probs @ new_best
        u = int(cand[int(np.argmin(vals))])
        kept.append(u)
        best = np.minimum(best, cost[:, u])
        remaining.remove(u)
    return kept, best


def _redistribute(cost: np.ndarray, probs: np.ndarray, kept: list[int]) -> np.ndarray:
    """Assign every atom's mass to its nearest kept atom; return kept-aligned probs."""
    kept_arr = np.array(kept)
    nearest = cost[:, kept_arr].argmin(axis=1)  # index into ``kept`` for every atom
    reduced = np.zeros(len(kept))
    np.add.at(reduced, nearest, probs)
    return reduced


def _kmeans_reduce(
    paths: np.ndarray, probs: np.ndarray, k: int, p: int, seed: int
) -> tuple[np.ndarray, np.ndarray, float]:
    from sklearn.cluster import KMeans

    km = KMeans(n_clusters=k, random_state=seed, n_init=10).fit(paths, sample_weight=probs)
    labels = km.labels_
    centroids = km.cluster_centers_
    reduced_probs = np.zeros(k)
    np.add.at(reduced_probs, labels, probs)
    d = np.sqrt(((paths - centroids[labels]) ** 2).sum(axis=1))
    distance = float((probs @ d**p) ** (1.0 / p))
    return centroids, reduced_probs, distance


def reduce_scenarios(
    scenarios: ScenarioSet,
    *,
    n_reduced: int,
    method: str = "forward",
    p: int = 2,
    seed: int = 0,
) -> tuple[ScenarioSet, float]:
    """Reduce ``scenarios`` to ``n_reduced`` representatives.

    Returns the reduced set and its Kantorovich-``p`` distance to the original.
    ``method="forward"`` (default) is Heitsch-Römisch fast forward selection;
    ``method="kmeans"`` is the clustering baseline. Reducing to the full size (or
    more) is the identity, distance 0.
    """
    if p < 1:
        raise ValueError(f"p must be >= 1; got {p}")
    s = scenarios.n_scenarios
    if n_reduced < 1:
        raise ValueError(f"n_reduced must be >= 1; got {n_reduced}")
    if n_reduced >= s:
        return scenarios, 0.0

    paths, probs = scenarios.paths, scenarios.probs

    if method == "forward":
        cost = _ground_dist(paths, paths) ** p
        kept, best = _forward_select(cost, probs, n_reduced)
        reduced_probs = _redistribute(cost, probs, kept)
        distance = float((probs @ best) ** (1.0 / p))
        reduced = ScenarioSet(paths[np.array(kept)], reduced_probs, scenarios.index)
        return reduced, distance

    if method == "kmeans":
        centroids, reduced_probs, distance = _kmeans_reduce(paths, probs, n_reduced, p, seed)
        return ScenarioSet(centroids, reduced_probs, scenarios.index), distance

    raise ValueError(f"unknown method {method!r}; expected 'forward' or 'kmeans'")
