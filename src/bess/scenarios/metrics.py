"""Probability metrics for scenario sets (R2.2).

The reduction distance is the Wasserstein-``p`` (Kantorovich) transport cost of
moving the fine measure's mass to the nearest support point of the coarse
measure. When the coarse support is a *subset* of the fine one (forward
selection) this is exact; for the k-means baseline (centroids are not atoms) it
is an upper bound on the true ``W_p``, used consistently so methods compare
fairly. See ``docs/formulation.md`` § R2.2.
"""

from __future__ import annotations

import numpy as np

from bess.scenarios.generate import ScenarioSet


def _ground_dist(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Pairwise Euclidean distances between rows of ``a`` (Sa, T) and ``b`` (Sb, T)."""
    diff = a[:, None, :] - b[None, :, :]
    return np.sqrt(np.einsum("ijk,ijk->ij", diff, diff))


def kantorovich_distance(a: ScenarioSet, b: ScenarioSet, *, p: int = 2) -> float:
    """Wasserstein-``p`` transport cost of ``a``'s mass onto ``b``'s support.

    ``D = ( Σ_i a.p_i · min_j ‖a.path_i − b.path_j‖^p )^{1/p}``. Ignores ``b``'s
    probabilities (it is the projection distance onto ``b``'s support), which is
    the quantity forward selection minimizes.
    """
    if p < 1:
        raise ValueError(f"p must be >= 1; got {p}")
    dmin = _ground_dist(a.paths, b.paths).min(axis=1)
    return float((a.probs @ dmin**p) ** (1.0 / p))
