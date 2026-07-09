"""CVaR of a discrete loss distribution (Rockafellar-Uryasev).

Formulation: ``docs/formulation.md`` § R2.3. Pure numpy; the exact discrete
Conditional Value-at-Risk and its Value-at-Risk minimiser, used both as the
gate's hand-checkable oracle and to score a solved two-stage schedule.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def cvar_from_losses(
    losses: Sequence[float] | np.ndarray,
    probs: Sequence[float] | np.ndarray,
    alpha: float,
) -> tuple[float, float]:
    """Return ``(CVaR_α, VaR_α)`` of a discrete loss distribution.

    ``CVaR_α(L) = min_η [ η + (1/(1-α))·Σ_s p_s (L_s - η)^+ ]`` (Rockafellar-
    Uryasev). The objective is convex and piecewise-linear in ``η`` with kinks at
    the loss atoms, so the minimum is attained at one of them; the smallest
    minimiser is the VaR (the α-quantile of the loss).
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must lie in (0, 1); got {alpha}")
    loss = np.asarray(losses, dtype=float)
    p = np.asarray(probs, dtype=float)
    if loss.shape != p.shape:
        raise ValueError(f"losses and probs must have equal shape; got {loss.shape} vs {p.shape}")

    scale = 1.0 / (1.0 - alpha)
    best_val = np.inf
    best_eta = float(loss.min())
    for eta in np.unique(loss):  # ascending ⇒ first (smallest) minimiser wins
        val = float(eta) + scale * float(np.sum(p * np.maximum(loss - eta, 0.0)))
        if val < best_val - 1e-15:
            best_val = val
            best_eta = float(eta)
    return best_val, best_eta
