"""Context layer contracts — typed layers and the layered context container.

A layer is a slice of context with a type, provenance, and optional guardrail
marker. The container is assembled deterministically by the ContextAssembler;
the PromptBuilder renders it. Layers carry plain-data content; formatting is
the builder's responsibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class LayerType(StrEnum):
    """The six context layers, ordered from most to least granular."""

    GLOBAL = "global"
    USER = "user"
    PROJECT = "project"
    TASK = "task"
    RESEARCH = "research"
    RETRIEVED = "retrieved"


# Higher value = higher precedence (more important, wins conflicts).
LAYER_PRECEDENCE: dict[LayerType, int] = {
    LayerType.RETRIEVED: 0,
    LayerType.RESEARCH: 1,
    LayerType.GLOBAL: 2,
    LayerType.PROJECT: 3,
    LayerType.USER: 4,
    LayerType.TASK: 5,
}

# Immutable layers: never dropped, never truncated.
GUARDRAIL_LAYERS: frozenset[LayerType] = frozenset({LayerType.TASK})


@dataclass
class Layer:
    """A single slice of context."""

    type: LayerType
    content: str
    source: str = ""
    guardrail: bool = False
    tokens: int = 0
    trace: dict | None = None
    priority: int = 0

    @property
    def is_guardrail(self) -> bool:
        return self.guardrail or self.type in GUARDRAIL_LAYERS

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "source": self.source,
            "guardrail": self.is_guardrail,
            "tokens": self.tokens,
            "trace": self.trace,
            "priority": self.priority,
            "content": self.content,
        }


@dataclass
class LayeredContext:
    """Ordered container of context layers."""

    layers: list[Layer] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.layers

    def add(self, layer: Layer) -> None:
        self.layers.append(layer)

    def by_type(self, layer_type: LayerType) -> list[Layer]:
        return [layer for layer in self.layers if layer.type is layer_type]

    def total_tokens(self) -> int:
        return sum(layer.tokens for layer in self.layers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_tokens": self.total_tokens(),
            "layers": [layer.to_dict() for layer in self.layers],
        }


def empty_layers() -> LayeredContext:
    """Safe factory — a fallback boundary never raises."""
    return LayeredContext()
