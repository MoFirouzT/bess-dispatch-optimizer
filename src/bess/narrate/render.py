"""Placeholder substitution and the deterministic fallback (R2.4b).

Spec: ``docs/specs/dual-narration.md`` § "Placeholders", § "Fallback".

Every number a reader sees is produced here, from the ``Explanation``, never by the
model. ``PLACEHOLDER`` is also the pattern `verify` strips before looking for stray
digits, so the two stay in step by construction.
"""

from __future__ import annotations

import re

from bess.explain.duals import Explanation
from bess.narrate.claims import Claim, Narration

# `{name:index}`, or the bare `{objective}`. Anchored to the same syntax the prompt
# tells the model to use.
PLACEHOLDER = re.compile(r"\{(objective|price|mu|band_low|band_high|slippage|soc|time):?(\d*)\}")

# Which collection each placeholder indexes into; `objective` indexes nothing.
DOMAIN: dict[str, str] = {
    "objective": "none",
    "price": "period",
    "mu": "run",
    "band_low": "period",
    "band_high": "period",
    "slippage": "period",
    "soc": "period",
    "time": "period",
}


class UnresolvablePlaceholder(ValueError):
    """A placeholder names a field that is absent (a band edge on an unpinned run)."""


def resolve(name: str, index: int, exp: Explanation) -> str:
    """The rendered text for one placeholder. Raises if the field is absent."""
    if name == "objective":
        return f"{exp.schedule.objective:.2f}"
    if name == "mu":
        return f"{exp.runs[index].water_value_eur_mwh:.2f}"
    if name == "time":
        # The period index, not a clock label: `Explanation` carries no dt, and an
        # index the claim already declared in `refs` is sourced either way.
        return f"period {index}"
    if name == "soc":
        return f"{exp.schedule.soc[index]:.3f}"

    period = exp.periods[index]
    value = {
        "price": period.price_eur_mwh,
        "band_low": period.band_low_eur_mwh,
        "band_high": period.band_high_eur_mwh,
        "slippage": period.breakeven_slippage_eur_mwh,
    }[name]
    if value is None:
        raise UnresolvablePlaceholder(f"{name} is not reported at period {index}")
    return f"{value:.2f}"


def render_claim(claim: Claim, exp: Explanation) -> str:
    """One claim's sentence with its placeholders substituted."""

    def sub(match: re.Match[str]) -> str:
        name, raw = match.group(1), match.group(2)
        return resolve(name, int(raw) if raw else 0, exp)

    return PLACEHOLDER.sub(sub, claim.text)


def render(narration: Narration, exp: Explanation) -> str:
    """The verified narrative. Call only on a narration `verify` accepted."""
    return " ".join(render_claim(c, exp) for c in narration.claims)


def fallback(exp: Explanation) -> str:
    """The deterministic narrative, used whenever the generated one is not served.

    Unlike the R1.5 solver breaker, whose greedy fallback is a worse *schedule*, this
    is the same facts in duller words: correct, and merely less readable. It names
    itself so it cannot be mistaken for the verified form (spec decision 6).
    """
    lines = [
        "Generated narration was unavailable or failed verification, so this is the "
        "deterministic summary.",
        f"Objective {exp.schedule.objective:.2f} EUR.",
    ]
    previous: str | None = None
    for t, period in enumerate(exp.periods):
        if period.action != previous:
            lines.append(f"Period {t}: {period.reason}")
            previous = period.action
    return "\n".join(lines)
