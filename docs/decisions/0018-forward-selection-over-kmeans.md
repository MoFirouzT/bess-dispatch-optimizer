# ADR-0018: Fast forward selection is the primary reducer; k-means is the compared baseline

**Status:** Accepted
**Date:** 2026-07-08
**Supersedes / Superseded by:** none

## Context

Generation yields 200 to 500 equiprobable paths; the R2.3 stochastic program's size (and
solve time) scale with the scenario count, so R2.2 must reduce to ~50 representatives
while preserving the distribution. Two families are on the table: probability-metric
reduction (Dupačová/Gröwe-Kuska/Römisch and Heitsch-Römisch, 2003) and clustering
(k-means on the paths). The choice matters because it decides what "preserved" means and
whether the reduced set carries a stability guarantee or only a heuristic resemblance.

## Decision

Use **fast forward selection** (Heitsch-Römisch) as the primary reducer: greedily grow
the kept set to minimize the Kantorovich distance to the original, then redistribute each
deleted atom's probability to its nearest kept atom. Keep **k-means** (centroids as
representatives, cluster mass as probability) as the baseline the gate compares against,
mirroring the CQR-vs-split baseline pattern of [ADR-0014](0014-cqr-over-split-conformal.md).

## Rationale

- **A published stability bound.** Forward selection targets the Kantorovich distance,
  for which stochastic-programming stability theory bounds the change in optimal value by
  that distance. The reduction is decision-relevant, not cosmetic.
- **The reduced measure stays valid by construction.** The redistribution rule conserves
  mass and keeps representatives as *original* atoms (real price paths), so nothing
  downstream optimizes against a synthetic centroid that never occurs.
- **k-means earns its keep as a baseline, not the method.** Its centroids are averaged
  paths (not atoms) and it minimizes squared Euclidean inertia, not the Kantorovich
  distance; retaining it lets the gate show the governed method does real work (its
  distance is no larger than k-means's and than a random subset's).

## Consequences

- Forward selection is `O(k · S^2)` in the number of atoms; fine at `S ~ 500`, and
  vectorized over candidates it stays in the main CI job (pure numpy, no new dependency).
- k-means pulls in scikit-learn (already the `forecast` group's dependency); it is imported
  lazily so the primary path and its gates need no optional group.
- The gate asserts the exact hand-computed forward-selection reduction on a tiny set
  (golden oracle), then the behavioral properties (monotone trade-off, beats-random,
  mass conservation) on generated sets.

## Alternatives considered

- **k-means / k-medoids as the primary method**: rejected as governed method; no
  Kantorovich-distance guarantee, and centroids are not real scenarios. Kept as baseline.
- **Backward reduction** (delete atoms one at a time): the same probability-metric family
  and an equally valid Heitsch-Römisch algorithm; forward selection is preferred when the
  kept count is far smaller than the original count (our case, 50 of ~300), where it does
  less work.
- **Exact minimum-distance subset**: combinatorial, not tractable; forward selection is
  the standard greedy surrogate.
