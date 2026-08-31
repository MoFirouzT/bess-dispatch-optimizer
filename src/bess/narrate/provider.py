"""The provider boundary: the one place this project talks to a language model (R2.4b).

Spec: ``docs/specs/dual-narration.md`` § "Interfaces".

`Provider` has one method, so every gate injects a recorded or deliberately hostile
implementation and no test opens a socket. `AnthropicProvider` is the only thing in
the package that imports the SDK, and the SDK is an optional extra: an install
without it still serves the fallback.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from bess.narrate.claims import Narration

if TYPE_CHECKING:  # pragma: no cover - typing only
    from bess.narrate.narrate import NarrationConfig


class Provider(Protocol):
    """Turn a prompt into a `Narration`, or raise.

    Every failure is a raise: transport, timeout, refusal, malformed JSON, schema
    violation. `narrate` maps all of them onto the same fallback, so a provider never
    has to decide what a failure means.
    """

    def narrate(self, prompt: str, config: NarrationConfig) -> Narration: ...


class RecordedProvider:
    """Returns a fixed narration. The gates' stand-in for a model."""

    def __init__(self, narration: Narration) -> None:
        self._narration = narration

    def narrate(self, prompt: str, config: NarrationConfig) -> Narration:
        return self._narration


class RaisingProvider:
    """Raises a given exception. Covers transport errors and timeouts."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    def narrate(self, prompt: str, config: NarrationConfig) -> Narration:
        raise self._error


class MalformedProvider:
    """Raises as the SDK's parse step does on output that is not the schema."""

    def narrate(self, prompt: str, config: NarrationConfig) -> Narration:
        raise ValueError("response did not validate against the Narration schema")


class AnthropicProvider:
    """The live provider.

    Not exercised by any gate: CI runs with no credential and no network, and the
    live tier that does exercise it is opt-in (spec acceptance gate). Until that tier
    has run, the request shape here is unverified against the API.
    """

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    def narrate(self, prompt: str, config: NarrationConfig) -> Narration:
        client = self._client
        if client is None:
            import anthropic  # imported lazily: an optional extra

            client = anthropic.Anthropic(timeout=config.timeout_s, max_retries=0)
        extra = {"output_config": {"effort": config.effort}} if config.effort else {}
        response = client.messages.parse(
            model=config.model,
            max_tokens=config.max_tokens,
            messages=[{"role": "user", "content": prompt}],
            output_format=Narration,
            **extra,
        )
        parsed = response.parsed_output
        if parsed is None:
            raise ValueError("the model returned no parsed output")
        return parsed
