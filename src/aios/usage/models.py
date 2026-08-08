"""UsageRecord — normalized token accounting across heterogeneous providers.

UsageRecord is the shared contract. Agents populate it from runtime adapter
output. TelemetryEngine consumes it. PricingResolver calculates cost from it.

No single provider determines the shape — every field is optional and the
contract normalizes resiliently via ``from_provider()``.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

SENSITIVE_KEYS = frozenset({
    "prompt",
    "messages",
    "authorization",
    "api_key",
    "token",
    "secret",
})
SENSITIVE_SUBSTRINGS = frozenset({"key", "secret", "token", "auth"})


def sanitize_provider_raw(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Remove sensitive keys from provider payload before persistence.

    Strips values for known sensitive top-level keys and any key whose
    *name* contains a sensitive substring. Operates on a shallow copy of
    the top-level dict; nested objects are *not* recursively walked.
    """
    if raw is None:
        return None
    sanitized: dict[str, Any] = {}
    for key, value in raw.items():
        lower = key.lower()
        sensitive = (
            key in SENSITIVE_KEYS
            or lower in SENSITIVE_KEYS
            or any(sub in lower for sub in SENSITIVE_SUBSTRINGS)
        )
        if sensitive:
            sanitized[key] = "[redacted]"
        else:
            sanitized[key] = value
    return sanitized


@dataclass
class UsageRecord:
    """Normalized token usage from any provider.

    Every field is optional — providers report different subsets (OpenAI
    uses ``input_tokens``, Ollama uses ``prompt_eval_count``). Callers
    use ``from_provider()`` to build a normalized record; consumers
    never inspect provider-specific payloads directly.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None
    reasoning_tokens: int | None = None
    context_tokens: int | None = None

    execution_id: str = ""
    agent: str = ""
    model: str = ""
    provider: str = ""
    timestamp: str = ""

    provider_raw: dict[str, Any] | None = None

    @classmethod
    def from_provider(
        cls,
        payload: dict[str, Any],
        provider: str,
        **meta: Any,
    ) -> "UsageRecord":
        """Build a normalized record from provider-format payload.

        Tries to extract known token fields by common provider naming
        conventions. Unknown fields are preserved in ``provider_raw``.
        Missing fields are left at ``None`` — no zero-filling, no
        guessing.

        Common provider mappings
        ------------------------
        * OpenAI / Anthropic: ``input_tokens`` / ``output_tokens``
        * Ollama:              ``prompt_eval_count`` / ``eval_count``
        * DeepSeek:            ``prompt_tokens`` / ``completion_tokens``
        """
        input_tokens = payload.get("input_tokens")
        if input_tokens is None:
            input_tokens = payload.get("prompt_tokens")
        if input_tokens is None:
            input_tokens = payload.get("prompt_eval_count")

        output_tokens = payload.get("output_tokens")
        if output_tokens is None:
            output_tokens = payload.get("completion_tokens")
        if output_tokens is None:
            output_tokens = payload.get("eval_count")

        total_tokens = payload.get("total_tokens")
        if total_tokens is None:
            total_tokens = payload.get("total_count")

        cached_tokens = payload.get("cached_tokens")
        if cached_tokens is None:
            cached_tokens = payload.get("cache_read_input_tokens")

        reasoning_tokens = payload.get("reasoning_tokens")

        context_tokens = payload.get("context_tokens")

        return cls(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_tokens=cached_tokens,
            reasoning_tokens=reasoning_tokens,
            context_tokens=context_tokens,
            provider_raw=sanitize_provider_raw(payload),
            provider=provider,
            timestamp=meta.get("timestamp", datetime.now(UTC).isoformat()),
            execution_id=meta.get("execution_id", ""),
            agent=meta.get("agent", ""),
            model=meta.get("model", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cached_tokens": self.cached_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "context_tokens": self.context_tokens,
            "execution_id": self.execution_id,
            "agent": self.agent,
            "model": self.model,
            "provider": self.provider,
            "timestamp": self.timestamp,
            "provider_raw": self.provider_raw,
        }

    @property
    def has_any_tokens(self) -> bool:
        """True when at least one token count is populated."""
        return any(
            v is not None
            for v in (
                self.input_tokens,
                self.output_tokens,
                self.total_tokens,
                self.cached_tokens,
                self.reasoning_tokens,
                self.context_tokens,
            )
        )
