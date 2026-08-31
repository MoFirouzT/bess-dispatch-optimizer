"""Dual-grounded narration of a solved dispatch (R2.4b).

Spec: ``docs/specs/dual-narration.md``.

Turns the R2.4 ``Explanation`` into prose in which **the language model never emits
a number**. The model returns an ordered list of typed claims whose sentences carry
placeholders (``{price:3}``, ``{mu:0}``); a deterministic renderer substitutes them
from the ``Explanation``. A wrong number is therefore not unlikely, it is
unrepresentable, and verification is a predicate over a closed vocabulary rather
than an exercise in reading prose.

This is the only package in the core chain that reaches the network, which is why it
sits *above* ``bess.explain`` rather than inside it: that layer stays offline and
deterministic. It imports ``explain``/``optimizer``/``assets`` and must never import
``bess.api`` (import-linter contract).
"""

from bess.narrate.claims import CLAIM_TYPES, Claim, Narration
from bess.narrate.narrate import NarrationConfig, NarrationResult, narrate
from bess.narrate.render import fallback, render
from bess.narrate.verify import verify

__all__ = [
    "CLAIM_TYPES",
    "Claim",
    "Narration",
    "NarrationConfig",
    "NarrationResult",
    "fallback",
    "narrate",
    "render",
    "verify",
]
