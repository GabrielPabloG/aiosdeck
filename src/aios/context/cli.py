"""CLI rendering for context layer inspection — `aios plan --debug-context`."""

from __future__ import annotations

import json
from typing import Any


def render_layer_tree(result: object, as_json: bool) -> str:
    """Render a ContextAssemblyResult as a text tree or JSON."""
    if as_json:
        to_dict = getattr(result, "to_dict", None)
        data = to_dict() if callable(to_dict) else {}
        return json.dumps(data, indent=2)

    lines = ["Context Layers"]
    for layer in result.layers:  # type: ignore[attr-defined]
        lines.append(_layer_line(layer))
    lines.append("")
    lines.append(f"- total: {result.total_tokens} tokens / budget {result.budget_tokens}")  # type: ignore[attr-defined]
    lines.append(f"- truncated: {result.truncated}")  # type: ignore[attr-defined]
    lines.append(f"- dropped_duplicates: {result.dropped_duplicates}")  # type: ignore[attr-defined]
    if result.audit:  # type: ignore[attr-defined]
        lines.append("")
        lines.append("Audit:")
        for entry in result.audit:  # type: ignore[attr-defined]
            lines.append(_audit_line(entry))
    return "\n".join(lines)


def _layer_line(layer: Any) -> str:
    parts = [f"  {layer.type.value}", f"source={layer.source}", f"tokens={layer.tokens}"]
    if layer.is_guardrail:
        parts.append("guardrail")
    if layer.trace:
        trace = layer.trace
        parts.append(f"trace={trace.get('source_id', '')}:{trace.get('position', '')}")
    return " | ".join(parts)


def _audit_line(entry: dict) -> str:
    return (
        f"  - {entry.get('action')} {entry.get('layer_type')} "
        f"source={entry.get('source')} "
        f"tokens {entry.get('tokens_before')}->{entry.get('tokens_after')}"
        f" ({entry.get('reason')})"
    )
