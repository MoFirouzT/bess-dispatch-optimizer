"""The verifier: seven rejection rules over a whole narration (R2.4b).

Spec: ``docs/specs/dual-narration.md`` § "Rejection rules".

Rejection is **whole-response**, never per-claim. Dropping one bad claim would leave
a narrative whose provenance depends on which claims happened to survive, which is
not a thing the gate can characterise (spec decision 3).
"""

from __future__ import annotations

from bess.explain.duals import Explanation
from bess.narrate.claims import CLAIM_TYPES, Claim, Narration, holds, in_range
from bess.narrate.render import DOMAIN as PLACEHOLDER_DOMAIN
from bess.narrate.render import PLACEHOLDER, UnresolvablePlaceholder, resolve

DEFAULT_MAX_CLAIMS = 8


def _claim_rejection(claim: Claim, exp: Explanation) -> str | None:
    """The first rule this claim breaks, or None."""
    if claim.type not in CLAIM_TYPES:
        return "unknown_type"

    # Rule 1: any decimal digit outside a placeholder. Checked before anything that
    # could accept the claim, because it is the rule the whole design rests on.
    if any(ch.isdigit() for ch in PLACEHOLDER.sub("", claim.text)):
        return "digit_in_text"

    if not in_range(claim, exp):
        return "bad_refs"

    # Rule 5: a claim may only quote indices it declared. Without this a claim about
    # period 0 could render period 9's price and still pass its own predicate.
    for match in PLACEHOLDER.finditer(claim.text):
        name, raw = match.group(1), match.group(2)
        if PLACEHOLDER_DOMAIN[name] == "none":
            continue
        if not raw or int(raw) not in claim.refs:
            return "foreign_placeholder"
        limit = len(exp.periods) if PLACEHOLDER_DOMAIN[name] == "period" else len(exp.runs)
        if not 0 <= int(raw) < limit:
            return "foreign_placeholder"

    if not holds(claim, exp):
        return "predicate_failed"

    # A band edge is None on an unpinned run, so a placeholder can be well-formed and
    # still have nothing to resolve to.
    for match in PLACEHOLDER.finditer(claim.text):
        name, raw = match.group(1), match.group(2)
        try:
            resolve(name, int(raw) if raw else 0, exp)
        except (UnresolvablePlaceholder, IndexError):
            return "unresolvable_placeholder"
    return None


def verify(
    narration: Narration, exp: Explanation, *, max_claims: int = DEFAULT_MAX_CLAIMS
) -> str | None:
    """None if every claim holds and every placeholder resolves; else the rule that fired.

    Total over any narration and any explanation: it returns a rule rather than
    raising, which is what lets `narrate` treat every rejection the same way.
    """
    if not narration.claims or len(narration.claims) > max_claims:
        return "claim_count"
    # Rule 1 is checked across every claim before any other rule runs. A literal digit
    # anywhere is the one failure whose report must not depend on which claim happened
    # to be examined first: it is the rule the whole construction rests on.
    for claim in narration.claims:
        if any(ch.isdigit() for ch in PLACEHOLDER.sub("", claim.text)):
            return "digit_in_text"
    for claim in narration.claims:
        rejection = _claim_rejection(claim, exp)
        if rejection is not None:
            return rejection
    return None
