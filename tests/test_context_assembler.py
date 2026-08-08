"""Tests for ContextAssembler — layer collection within agent budgets."""

import aios.knowledge  # noqa: F401  (load before selector to avoid circular import)

from aios.agents import Task
from aios.context.assembler import ContextAssembler
from aios.context.layers import LayerType
from aios.context.packet import ContextPacket, ProjectInfo, ToolsInfo
from aios.retrieval.selector import ContextBudget


def _make_context() -> ContextPacket:
    ctx = ContextPacket()
    ctx.project = ProjectInfo(name="demo", root="/tmp/demo", language="python")
    ctx.tools = ToolsInfo(linter="ruff", formatter="ruff", test_runner="pytest")
    ctx.git.branch = "main"
    ctx.git.status = "clean"
    ctx.skills = ["project-dna", "coding-style"]
    return ctx


def _assemble(
    task_desc: str = "Add OAuth login",
    context: ContextPacket | None = None,
    agent: str = "developer",
    budget: ContextBudget | None = None,
):
    assembler = ContextAssembler(budget=budget)
    return assembler.assemble(Task(description=task_desc), context or _make_context(), agent=agent)


class TestLayerCollection:
    def test_task_and_project_present(self):
        result = _assemble()
        types = {layer.type for layer in result.layers}
        assert LayerType.TASK in types
        assert LayerType.PROJECT in types

    def test_task_is_guardrail(self):
        result = _assemble()
        task = next(layer for layer in result.layers if layer.type is LayerType.TASK)
        assert task.is_guardrail
        assert task.content == "Add OAuth login"
        assert task.source == "task"

    def test_project_content_plain_data(self):
        result = _assemble()
        project = next(layer for layer in result.layers if layer.type is LayerType.PROJECT)
        assert project.source == "packet"
        assert not project.is_guardrail
        assert "python" in project.content
        assert "ruff" in project.content
        assert "main" in project.content

    def test_global_and_user_empty_by_default(self):
        result = _assemble()
        types = {layer.type for layer in result.layers}
        assert LayerType.GLOBAL not in types
        assert LayerType.USER not in types

    def test_ordering_task_before_project(self):
        result = _assemble()
        types = [layer.type for layer in result.layers]
        assert types.index(LayerType.TASK) < types.index(LayerType.PROJECT)


class TestBudget:
    def test_budget_from_context_budget(self):
        budget = ContextBudget(overrides={"developer": 200})
        result = _assemble(agent="developer", budget=budget)
        assert result.budget_tokens == 200

    def test_task_intact_with_tiny_budget(self):
        big_task = " ".join(["word"] * 100)
        result = _assemble(task_desc=big_task, agent="developer")
        task = next(layer for layer in result.layers if layer.type is LayerType.TASK)
        assert task.tokens == 100

    def test_unknown_agent_fallback_budget(self):
        result = _assemble(agent="unknown_agent")
        assert result.budget_tokens == 3000


class TestFailSafe:
    def test_empty_context_still_assembles(self):
        result = _assemble(context=ContextPacket())
        assert any(layer.type is LayerType.TASK for layer in result.layers)

    def test_budget_none_default(self):
        result = _assemble(agent="planner")
        assert result.budget_tokens == 3000

    def test_never_raises(self):
        assembler = ContextAssembler()
        result = assembler.assemble(Task(description="x"), None, agent="developer")
        assert result.layers
