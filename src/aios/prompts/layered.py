"""Layered prompt sections — render context layers into prompt text.

Separation of responsibilities: layers carry plain-data content; this module
formats them. Used only when PromptBuilder receives an explicit layered
context (opt-in), leaving the default path byte-identical.
"""

from __future__ import annotations

from aios.context.layers import LayeredContext, LayerType


def layers_by_type(layered: LayeredContext) -> dict[LayerType, object]:
    result: dict[LayerType, object] = {}
    for layer in layered.layers:
        result.setdefault(layer.type, layer)
    return result


def task_section(by_type: dict[LayerType, object]) -> str:
    layer = by_type.get(LayerType.TASK)
    if layer is None:
        return ""
    return f"## Task\n{layer.content}"


def project_section(by_type: dict[LayerType, object]) -> str:
    layer = by_type.get(LayerType.PROJECT)
    if layer is None:
        return ""
    return f"## Project Context\n{layer.content}"


def research_section(by_type: dict[LayerType, object]) -> str:
    layer = by_type.get(LayerType.RESEARCH)
    if layer is None:
        return ""
    return f"## Research\n{layer.content}"


def knowledge_section(layered: LayeredContext) -> str:
    layers = [
        layer for layer in layered.layers if layer.type is LayerType.RETRIEVED and layer.content
    ]
    if not layers:
        return ""
    lines = ["[Knowledge]"]
    for i, layer in enumerate(layers, 1):
        trace = layer.trace or {}
        source_path = trace.get("source_path", "")
        score = trace.get("score", "")
        position = trace.get("position", "")
        source = f"retrieved/{source_path}" if source_path else "retrieved"
        meta = f"(score={score}) [pos={position}]" if score else ""
        lines.append(f"[{i}] source={source} {meta}")
        lines.append(layer.content)
        lines.append("")
    return "\n".join(lines)


def audit_section(layered: LayeredContext) -> str:
    lines = ["[Audit]"]
    for layer in layered.layers:
        guardrail = " [guardrail]" if layer.is_guardrail else ""
        lines.append(
            f"- {layer.type.value} (source={layer.source}) tokens={layer.tokens}{guardrail}"
        )
    total = getattr(layered, "total_tokens", None)
    if callable(total):
        total = total()
    lines.append(f"- total: {total or 0} tokens")
    budget = getattr(layered, "budget_tokens", None)
    if budget is not None:
        lines.append(f"- budget: {budget} tokens")
        truncated = getattr(layered, "truncated", False)
        dropped = getattr(layered, "dropped_duplicates", 0)
        lines.append(f"- truncated: {truncated}")
        lines.append(f"- dropped_duplicates: {dropped}")
    return "\n".join(lines)
