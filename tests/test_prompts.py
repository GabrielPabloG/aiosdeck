"""Tests for PromptBuilder — task + context → prompt string."""

from unittest.mock import MagicMock

from aios.agents import Task
from aios.agents.developer import DeveloperAgent
from aios.context.packet import ContextPacket, ProjectInfo, ToolsInfo
from aios.memory.models import Convention, Decision, ProjectKnowledge
from aios.prompts import PromptBuilder


def _make_context(language: str = "python") -> ContextPacket:
    ctx = ContextPacket()
    ctx.project = ProjectInfo(language=language, root="/tmp/test", name="test")
    ctx.tools = ToolsInfo(linter="ruff", formatter="black", test_runner="pytest")
    ctx.skills = ["project-dna", "coding-style"]
    return ctx


def test_build_has_all_sections():
    builder = PromptBuilder()
    ctx = _make_context()
    ctx.git.branch = "main"
    ctx.git.status = "clean"

    prompt = builder.build(Task(description="Write a test"), ctx)
    assert "## Task" in prompt
    assert "## Project Context" in prompt
    assert "## Git Status" in prompt
    assert "## Task" in prompt


def test_build_with_empty_memory():
    builder = PromptBuilder()
    ctx = _make_context()
    ctx.memory = None

    prompt = builder.build(Task(description="test"), ctx)
    assert "## Memory" not in prompt


def test_build_memory_content():
    builder = PromptBuilder()
    ctx = _make_context()
    knowledge = ProjectKnowledge(
        conventions=[Convention(rule="Use snake_case")],
        decisions=[Decision(title="SQLite")],
    )
    ctx.memory = knowledge

    prompt = builder.build(Task(description="test"), ctx)
    assert "## Memory" in prompt
    assert "Use snake_case" in prompt
    assert "SQLite" in prompt


def test_build_without_git():
    builder = PromptBuilder()
    ctx = _make_context()
    ctx.git.branch = ""

    prompt = builder.build(Task(description="test"), ctx)
    assert "unknown" in prompt


def test_developer_uses_builder():
    runtime = MagicMock()
    runtime.execute.return_value = "output"
    builder = MagicMock(wraps=PromptBuilder())

    agent = DeveloperAgent(runtime, builder=builder)
    ctx = _make_context()
    agent.execute(Task(description="Hello"), ctx)

    builder.build.assert_called_once()
