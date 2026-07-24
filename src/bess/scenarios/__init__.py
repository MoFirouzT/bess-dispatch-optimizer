"""scenarios — scenario generation + reduction (Heitsch-Römisch / k-means).

Turns the R2.1 interval forecast into a discrete, probability-weighted set of
price paths (residual-path bootstrap), then reduces it to a small representative
set that preserves the distribution within a Kantorovich-distance tolerance.
Feeds ``stochastic``. (R2.2)

Pure numpy/pandas on the forward-selection path (runs without any optional
group); the k-means baseline imports scikit-learn lazily.
"""

from __future__ import annotations

from bess.scenarios.generate import ScenarioSet, generate_scenarios
from bess.scenarios.metrics import kantorovich_distance
from bess.scenarios.reduce import reduce_scenarios
from bess.scenarios.tail import ConditionalTailModel, TailModel

__all__ = [
    "ConditionalTailModel",
    "ScenarioSet",
    "TailModel",
    "generate_scenarios",
    "kantorovich_distance",
    "reduce_scenarios",
]
