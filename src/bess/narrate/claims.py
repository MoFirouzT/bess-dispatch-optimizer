"""The claim vocabulary and its predicates (R2.4b).

Spec: ``docs/specs/dual-narration.md`` § "The claim vocabulary".

Six claim types, each with one predicate over the R2.4 ``Explanation``. A claim is
accepted only where its predicate holds, so the model chooses *which* true thing to
say and never *what is true*.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from bess.explain.duals import Explanation

# Band edges and prices agree to solver tolerance, not to the bit; the same 1e-6 the
# rest of the dual layer uses.
_TOL = 1e-6
# Two water values count as distinct above this, matching duals._PIN_TOL.
_STEP_TOL = 1e-5

ClaimType = Literal[
    "threshold_cross",
    "no_trade_band",
    "tie_break_ambiguous",
    "flat_run",
    "water_value_step",
    "slippage_margin",
]

CLAIM_TYPES: frozenset[str] = frozenset(
    (
        "threshold_cross",
        "no_trade_band",
        "tie_break_ambiguous",
        "flat_run",
        "water_value_step",
        "slippage_margin",
    )
)

# How many indices each type declares, and what those indices point at. Arity is
# checked before any predicate runs, so a predicate may assume its own shape.
ARITY: dict[str, int] = {
    "threshold_cross": 1,
    "no_trade_band": 1,
    "tie_break_ambiguous": 1,
    "flat_run": 1,
    "water_value_step": 2,
    "slippage_margin": 1,
}
# "period" or "run": which collection the type's refs index into.
DOMAIN: dict[str, str] = {
    "threshold_cross": "period",
    "no_trade_band": "period",
    "tie_break_ambiguous": "period",
    "flat_run": "run",
    "water_value_step": "run",
    "slippage_margin": "period",
}


class Claim(BaseModel):
    """One thing the narrative asserts about the dispatch.

    ``text`` is a sentence whose every quantity is a placeholder. It is prose written
    by the model; it is never trusted to contain a number, and `verify` rejects it if
    it does.
    """

    type: ClaimType
    refs: list[int] = Field(min_length=1, max_length=2)
    text: str

    model_config = {"extra": "forbid"}


class Narration(BaseModel):
    """The model's whole output: an ordered list of claims and nothing else."""

    claims: list[Claim]

    model_config = {"extra": "forbid"}


def in_range(claim: Claim, exp: Explanation) -> bool:
    """Arity and index bounds. Checked before any predicate, which may then assume them."""
    if claim.type not in CLAIM_TYPES:
        return False
    if len(claim.refs) != ARITY[claim.type]:
        return False
    limit = len(exp.periods) if DOMAIN[claim.type] == "period" else len(exp.runs)
    return all(0 <= i < limit for i in claim.refs)


def holds(claim: Claim, exp: Explanation) -> bool:
    """Does this claim's predicate hold on this explanation?

    False for an out-of-range claim, so callers need not order the two checks.
    """
    if not in_range(claim, exp):
        return False

    if claim.type == "threshold_cross":
        p = exp.periods[claim.refs[0]]
        if p.action == "charge" and p.band_low_eur_mwh is not None:
            return p.price_eur_mwh <= p.band_low_eur_mwh + _TOL
        if p.action == "discharge" and p.band_high_eur_mwh is not None:
            return p.price_eur_mwh >= p.band_high_eur_mwh - _TOL
        return False

    if claim.type == "no_trade_band":
        p = exp.periods[claim.refs[0]]
        if p.action != "idle" or not exp.runs[p.run].pinned:
            return False
        if p.band_low_eur_mwh is None or p.band_high_eur_mwh is None:
            return False
        return p.band_low_eur_mwh - _TOL <= p.price_eur_mwh <= p.band_high_eur_mwh + _TOL

    if claim.type == "tie_break_ambiguous":
        return not exp.runs[exp.periods[claim.refs[0]].run].pinned

    if claim.type == "flat_run":
        return len(exp.runs[claim.refs[0]].periods) >= 2

    if claim.type == "water_value_step":
        i, j = claim.refs
        # Runs partition the horizon and split exactly where SoC leaves the interior
        # (duals._flat_runs), so adjacency already carries "SoC hit a bound". The
        # remaining content of the claim is that the water value actually moved.
        if j != i + 1:
            return False
        gap = exp.runs[i].water_value_eur_mwh - exp.runs[j].water_value_eur_mwh
        return abs(gap) > _STEP_TOL

    # slippage_margin
    return exp.periods[claim.refs[0]].breakeven_slippage_eur_mwh is not None
