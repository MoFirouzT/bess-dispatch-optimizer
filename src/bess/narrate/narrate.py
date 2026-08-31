"""The pipeline: prompt, verify, render, or fall back (R2.4b).

Spec: ``docs/specs/dual-narration.md``.

Every path out of here returns text. A narration failure is never an error: the
fallback carries the same facts in duller words, so returning it strictly beats a
503 (spec decision 2). That is the opposite of `/explain`, whose R1.5 fallback would
be a *worse schedule*, and the asymmetry is deliberate.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from bess.explain.duals import Explanation
from bess.narrate.claims import ARITY, DOMAIN, Narration
from bess.narrate.provider import AnthropicProvider, Provider
from bess.narrate.render import fallback, render
from bess.narrate.verify import DEFAULT_MAX_CLAIMS, verify

CREDENTIAL_ENV = "ANTHROPIC_API_KEY"


@dataclass(frozen=True)
class NarrationConfig:
    """Knobs, all of them configuration rather than code (spec § Parameters)."""

    model: str = "claude-opus-5"
    # The task is selection and phrasing, not reasoning. None omits `output_config`
    # entirely, which older models require: `effort` is rejected on Haiku 4.5.
    effort: str | None = "low"
    max_claims: int = DEFAULT_MAX_CLAIMS
    max_tokens: int = 2048
    # A slow narration falls back rather than delaying a schedule; no retries.
    # 20 s, not the 10 s first specified: measured Opus 5 latency is ~11 s median
    # and 15 s at the tail, so a 10 s budget fell back on roughly half of all good
    # narrations. `/explain/narrative` solves a MILP and re-solves an LP before it
    # narrates, so it was never a fast path (spec decision 8).
    timeout_s: float = 20.0


@dataclass(frozen=True)
class NarrationResult:
    """What the layer returns. `verified` is False exactly when `text` is the fallback."""

    text: str
    verified: bool
    rejection: str | None


def _facts(exp: Explanation) -> str:
    """The explanation as JSON, the only substrate the model is given."""
    return json.dumps(
        {
            "objective_eur": exp.schedule.objective,
            "soc_mwh": list(exp.schedule.soc),
            "runs": [
                {
                    "index": i,
                    "periods": list(r.periods),
                    "water_value_eur_mwh": r.water_value_eur_mwh,
                    "pinned": r.pinned,
                }
                for i, r in enumerate(exp.runs)
            ],
            "periods": [
                {
                    "index": t,
                    "action": p.action,
                    "price_eur_mwh": p.price_eur_mwh,
                    "water_value_eur_mwh": p.water_value_eur_mwh,
                    "run": p.run,
                    "band_low_eur_mwh": p.band_low_eur_mwh,
                    "band_high_eur_mwh": p.band_high_eur_mwh,
                    "breakeven_slippage_eur_mwh": p.breakeven_slippage_eur_mwh,
                }
                for t, p in enumerate(exp.periods)
            ],
        },
        sort_keys=True,
    )


# Each type's condition, stated to the model in the same words the verifier checks.
# The first live run rejected 100% of narrations against a prompt that named the types
# and not their conditions, so the model was inferring rules like "a step needs adjacent
# runs". Stating them is not prompt tuning: the verifier enforces them either way.
_PREDICATES: dict[str, str] = {
    "threshold_cross": (
        "the period's action is charge or discharge, and its price is on the side of "
        "the band edge that action implies"
    ),
    "no_trade_band": (
        "the period's action is idle, its run is pinned, and its price lies between "
        "band_low and band_high"
    ),
    "tie_break_ambiguous": "the period's run is NOT pinned",
    "flat_run": "the run covers two or more periods",
    "water_value_step": (
        "the two runs are ADJACENT (the second index is the first plus one) and their "
        "water values differ"
    ),
    "slippage_margin": "the period reports a non-null breakeven_slippage_eur_mwh",
}


def build_prompt(exp: Explanation, config: NarrationConfig) -> str:
    """The request. States the placeholder rule and every claim condition.

    Both are stated because both are checked. A claim whose condition does not hold is
    rejected, and rejection is whole-response, so one wrong claim discards the rest.
    """
    types = "\n".join(
        f"- {name}: {ARITY[name]} {DOMAIN[name]} index"
        f"{'es' if ARITY[name] > 1 else ''}. Valid only if {_PREDICATES[name]}."
        for name in sorted(ARITY)
    )
    return (
        "You are writing a short account of a battery dispatch for an energy trader.\n\n"
        "You must not write any digit. Every quantity is a placeholder that is "
        "substituted later from the solved model. The placeholders are "
        "{price:t}, {mu:i}, {band_low:t}, {band_high:t}, {slippage:t}, {soc:t}, "
        "{time:t} and {objective}. A claim may only use indices listed in its own "
        "refs. A sentence containing a literal digit causes the whole response to be "
        "discarded.\n\n"
        "{time:t} renders as the words 'period t', so do not write 'period' before "
        "it yourself.\n\n"
        "band_low and band_high are null on a period whose run is not pinned, and "
        "breakeven_slippage_eur_mwh is null at an idle period. A placeholder that "
        "resolves to null discards the whole response, so check the value is present "
        "before quoting it.\n\n"
        f"Claim types, each valid only under its condition:\n{types}\n\n"
        f"Return at most {config.max_claims} claims, ordered as they should be read. "
        "Every claim must satisfy its condition against the data below. One claim that "
        "does not discards the entire response, so prefer fewer claims you have "
        "checked to more you have not.\n\n"
        "Say what explains the shape of the day: which periods matter and how the "
        "runs connect. Do not restate every period.\n\n"
        f"The solved dispatch:\n{_facts(exp)}"
    )


def narrate(
    exp: Explanation,
    *,
    config: NarrationConfig | None = None,
    provider: Provider | None = None,
) -> NarrationResult:
    """Narrate a solved dispatch, falling back on any failure.

    With no provider and no credential in the environment, this returns the fallback
    without constructing a client, which is how CI runs the whole path offline.
    """
    config = config or NarrationConfig()
    if provider is None:
        if not os.environ.get(CREDENTIAL_ENV):
            return NarrationResult(fallback(exp), False, "no_credential")
        provider = AnthropicProvider()

    try:
        narration = provider.narrate(build_prompt(exp, config), config)
    except Exception as exc:  # every provider failure is one outcome: the fallback
        return NarrationResult(fallback(exp), False, f"provider_error: {type(exc).__name__}")

    if not isinstance(narration, Narration):
        return NarrationResult(fallback(exp), False, "malformed")

    rejection = verify(narration, exp, max_claims=config.max_claims)
    if rejection is not None:
        return NarrationResult(fallback(exp), False, rejection)
    return NarrationResult(render(narration, exp), True, None)
