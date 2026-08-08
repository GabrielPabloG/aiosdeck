"""ContextAssembler — collects raw layers and fits them to an agent budget.

Each layer carries plain-data content with provenance. The assembler applies
the SkillAssembler fallback boundary: any failure in a single layer's
collection degrades to an empty layer — never a raised exception.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aios.context.assembly import (
    DEFAULT_LAYER_CAPS,
    ContextAssemblyResult,
    assemble_layers,
)
from aios.context.layers import Layer, LayerType

if TYPE_CHECKING:
    from aios.context.packet import ContextPacket
    from aios.knowledge import KnowledgeEngine
    from aios.retrieval.selector import ContextBudget

logger = logging.getLogger("aios.context.assembler")


class ContextAssembler:
    """Orchestrates raw context -> ordered, budgeted, audited layers."""

    def __init__(
        self,
        knowledge: KnowledgeEngine | None = None,
        budget: ContextBudget | None = None,
    ) -> None:
        self._knowledge = knowledge
        from aios.retrieval.selector import ContextBudget  # noqa: PLC0415

        self._budget = budget or ContextBudget()

    def assemble(
        self,
        task,
        context: ContextPacket | None,
        *,
        agent: str = "developer",
    ) -> ContextAssemblyResult:
        budget_total = self._budget.for_agent(agent)
        layers: list[Layer] = []

        for label, builder in (
            ("global", self._build_global_layers),
            ("user", self._build_user_layers),
            ("project", lambda: self._build_project_layers(context)),
            ("task", lambda: self._build_task_layers(task)),
        ):
            layers.extend(self._collect(label, builder))

        return assemble_layers(layers, budget_total, caps=DEFAULT_LAYER_CAPS)

    # ------------------------------------------------------------------
    # Collectors — each returns [] on any failure (fallback boundary)
    # ------------------------------------------------------------------

    def _collect(self, label: str, builder) -> list[Layer]:
        try:
            return builder()
        except Exception:
            logger.warning("%s layer collection failed", label.capitalize(), exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Layer builders — plain-data content
    # ------------------------------------------------------------------

    def _build_global_layers(self) -> list[Layer]:
        return []

    def _build_user_layers(self) -> list[Layer]:
        return []

    def _build_project_layers(self, context: ContextPacket | None) -> list[Layer]:
        if context is None:
            return []
        lines = [
            f"Language: {context.project.language}",
            f"Root: {context.project.root}",
            f"Name: {context.project.name}",
            f"Linter: {context.tools.linter or 'none'}",
            f"Formatter: {context.tools.formatter or 'none'}",
            f"Test runner: {context.tools.test_runner or 'none'}",
            f"Git branch: {context.git.branch or 'unknown'}",
            f"Git status: {context.git.status}",
        ]
        if context.skills:
            lines.append(f"Skills: {', '.join(context.skills)}")
        content = "\n".join(lines)
        return [
            Layer(
                type=LayerType.PROJECT,
                content=content,
                source="packet",
                tokens=len(content.split()),
            )
        ]

    def _build_task_layers(self, task) -> list[Layer]:
        description = getattr(task, "description", "") or ""
        content = description.strip()
        if not content:
            return []
        return [
            Layer(
                type=LayerType.TASK,
                content=content,
                source="task",
                guardrail=True,
                tokens=len(content.split()),
            )
        ]
