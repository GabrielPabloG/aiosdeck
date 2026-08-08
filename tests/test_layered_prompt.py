"""Tests for layered prompt composition — opt-in, byte-identical fallback."""

import aios.knowledge  # noqa: F401  (load before selector to avoid circular import)

from aios.agents import Task
from aios.context.assembly import ContextAssemblyResult
from aios.context.layers import Layer, LayerType, LayeredContext
from aios.context.packet import ContextPacket, ProjectInfo, ToolsInfo
from aios.prompts import PromptBuilder


def _make_context() -> ContextPacket:
    ctx = ContextPacket()
    ctx.project = ProjectInfo(name="demo", root="/tmp/demo", language="python")
    ctx.tools = ToolsInfo(linter="ruff", formatter="ruff", test_runner="pytest")
    ctx.git.branch = "main"
    ctx.git.status = "clean"
    ctx.skills = ["project-dna"]
    return ctx


def _layered() -> LayeredContext:
    ctx = LayeredContext()
    ctx.add(
        Layer(type=LayerType.TASK, content="Add OAuth", source="task", guardrail=True, tokens=2)
    )
    ctx.add(
        Layer(
            type=LayerType.PROJECT,
            content="Language: python",
            source="packet",
            tokens=2,
        )
    )
    ctx.add(
        Layer(type=LayerType.RESEARCH, content="Use SQLite.", source="packet.research", tokens=2)
    )
    ctx.add(
        Layer(
            type=LayerType.RETRIEVED,
            content="Docs chunk.",
            source="selector",
            tokens=2,
            trace={"source_id": "doc-1", "source_path": "docs/a.md", "score": 0.9, "position": 0},
        )
    )
    return ctx


class TestByteIdenticalFallback:
    def test_layered_none_same_as_before(self):
        builder = PromptBuilder()
        ctx = _make_context()
        without = builder.build(Task(description="Test"), ctx, layered=None)
        baseline = builder.build(Task(description="Test"), ctx)
        assert without == baseline

    def test_empty_layered_same_as_before(self):
        builder = PromptBuilder()
        ctx = _make_context()
        prompt = builder.build(Task(description="Test"), ctx, layered=LayeredContext())
        baseline = builder.build(Task(description="Test"), ctx)
        assert prompt == baseline

    def test_empty_assembly_result_same_as_before(self):
        builder = PromptBuilder()
        ctx = _make_context()
        empty_result = ContextAssemblyResult()
        prompt = builder.build(Task(description="Test"), ctx, layered=empty_result)
        baseline = builder.build(Task(description="Test"), ctx)
        assert prompt == baseline


class TestLayeredComposition:
    def test_task_section_from_layer(self):
        builder = PromptBuilder()
        prompt = builder.build(Task(description="ignored"), _make_context(), layered=_layered())
        assert "## Task" in prompt
        assert "Add OAuth" in prompt

    def test_project_section_from_layer(self):
        builder = PromptBuilder()
        prompt = builder.build(Task(description="x"), _make_context(), layered=_layered())
        assert "## Project Context" in prompt
        assert "Language: python" in prompt

    def test_research_section_from_layer(self):
        builder = PromptBuilder()
        prompt = builder.build(Task(description="x"), _make_context(), layered=_layered())
        assert "## Research" in prompt
        assert "Use SQLite." in prompt

    def test_retrieved_knowledge_section_with_trace(self):
        builder = PromptBuilder()
        prompt = builder.build(Task(description="x"), _make_context(), layered=_layered())
        assert "[Knowledge]" in prompt
        assert "Docs chunk." in prompt
        assert "docs/a.md" in prompt

    def test_audit_block_present(self):
        builder = PromptBuilder()
        prompt = builder.build(Task(description="x"), _make_context(), layered=_layered())
        assert "[Audit]" in prompt
        assert "task" in prompt
        assert "project" in prompt

    def test_deterministic_output(self):
        builder = PromptBuilder()
        ctx = _make_context()
        layered = _layered()
        first = builder.build(Task(description="x"), ctx, layered=layered)
        second = builder.build(Task(description="x"), ctx, layered=layered)
        assert first == second
