"""Layer assembly — deterministic precedence, dedupe, budget, and audit.

Pure functions: order layers by precedence, drop duplicate content (first
by precedence wins), and fit layers within an agent's token budget while
never truncating or dropping guardrail layers.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from aios.context.layers import LAYER_PRECEDENCE, Layer, LayerType

# NOTE: aios.retrieval.selector is imported lazily inside functions because
# importing it at module scope creates a cycle (selector -> knowledge ->
# engine -> selector).

# Absolute token caps per layer type. 0 = no cap (RETRIEVED is bounded by the
# ContextSelector; TASK is a guardrail).
DEFAULT_LAYER_CAPS: dict[LayerType, int] = {
    LayerType.RETRIEVED: 0,
    LayerType.RESEARCH: 1500,
    LayerType.GLOBAL: 4000,
    LayerType.PROJECT: 4000,
    LayerType.USER: 4000,
    LayerType.TASK: 0,
}


def order_layers(layers: list[Layer]) -> list[Layer]:
    """Stable sort by precedence, highest first."""
    return sorted(layers, key=lambda layer: LAYER_PRECEDENCE[layer.type], reverse=True)


def _content_digest(content: str) -> str:
    normalized = " ".join(content.split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _audit_entry(action: str, layer: Layer, before: int, after: int, reason: str) -> dict:
    return {
        "action": action,
        "layer_type": layer.type.value,
        "source": layer.source,
        "tokens_before": before,
        "tokens_after": after,
        "reason": reason,
    }


def dedupe_layers(ordered: list[Layer], audit: list[dict] | None = None) -> tuple[list[Layer], int]:
    """Drop duplicate content; first-by-precedence wins. Returns (kept, dropped)."""
    audit = audit if audit is not None else []
    seen: set[str] = set()
    kept: list[Layer] = []
    dropped = 0
    for layer in ordered:
        digest = _content_digest(layer.content)
        if digest in seen:
            dropped += 1
            audit.append(
                _audit_entry(
                    "dropped_duplicate",
                    layer,
                    layer.tokens,
                    0,
                    "duplicate content; higher precedence wins",
                )
            )
            continue
        seen.add(digest)
        kept.append(layer)
    return kept, dropped


def truncate_layers(
    ordered: list[Layer],
    budget_total: int,
    caps: dict[LayerType, int] | None = None,
    audit: list[dict] | None = None,
) -> tuple[list[Layer], bool, list[dict]]:
    """Fit layers within an absolute budget. Guardrails are never cut.

    Returns (kept, truncated, audit). Layer-level caps are applied first;
    when the total still exceeds ``budget_total``, lower-precedence layers
    are dropped first, preserving higher-precedence content.
    """
    caps = caps or DEFAULT_LAYER_CAPS
    audit = audit if audit is not None else []
    truncated = False
    ordered = order_layers(ordered)

    from aios.retrieval.selector import _truncate_to_tokens  # noqa: PLC0415

    for layer in ordered:
        cap = caps.get(layer.type, 0)
        if cap and not layer.is_guardrail and layer.tokens > cap:
            before = layer.tokens
            layer.content = _truncate_to_tokens(layer.content, cap)
            layer.tokens = len(layer.content.split())
            audit.append(
                _audit_entry("truncated", layer, before, layer.tokens, f"layer cap {cap} tokens")
            )
            truncated = True

    guardrail_tokens = sum(layer.tokens for layer in ordered if layer.is_guardrail)
    budget_left = max(0, budget_total - guardrail_tokens)

    kept: list[Layer] = []
    for layer in ordered:
        if layer.is_guardrail:
            kept.append(layer)
            continue
        if layer.tokens <= budget_left:
            kept.append(layer)
            budget_left -= layer.tokens
            continue
        if budget_left > 0:
            before = layer.tokens
            layer.content = _truncate_to_tokens(layer.content, budget_left)
            layer.tokens = len(layer.content.split())
            audit.append(
                _audit_entry(
                    "truncated",
                    layer,
                    before,
                    layer.tokens,
                    f"over budget; truncated to {budget_left} tokens",
                )
            )
            truncated = True
            kept.append(layer)
            budget_left = 0
        else:
            audit.append(_audit_entry("dropped", layer, layer.tokens, 0, "over budget; dropped"))
            truncated = True

    return kept, truncated, audit


@dataclass
class ContextAssemblyResult:
    layers: list[Layer] = field(default_factory=list)
    total_tokens: int = 0
    budget_tokens: int = 0
    truncated: bool = False
    dropped_duplicates: int = 0
    audit: list[dict] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.layers

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_tokens": self.total_tokens,
            "budget_tokens": self.budget_tokens,
            "truncated": self.truncated,
            "dropped_duplicates": self.dropped_duplicates,
            "layers": [layer.to_dict() for layer in self.layers],
            "audit": self.audit,
        }


def assemble_layers(
    layers: list[Layer],
    budget_total: int,
    caps: dict[LayerType, int] | None = None,
) -> ContextAssemblyResult:
    """Order → dedupe → truncate, returning an audit-traced result."""
    ordered = order_layers(layers)
    audit: list[dict] = []
    kept, dropped_duplicates = dedupe_layers(ordered, audit=audit)
    for layer in kept:
        audit.append(_audit_entry("added", layer, layer.tokens, layer.tokens, "retained"))

    final, truncated, audit = truncate_layers(kept, budget_total, caps=caps, audit=audit)
    return ContextAssemblyResult(
        layers=final,
        total_tokens=sum(layer.tokens for layer in final),
        budget_tokens=budget_total,
        truncated=truncated,
        dropped_duplicates=dropped_duplicates,
        audit=audit,
    )
