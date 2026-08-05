"""Tests for ReviewerAgent — capabilities, execution, JSON verdict parsing."""

from unittest.mock import MagicMock

from aios.agents.reviewer import ReviewerAgent
from aios.context.packet import ContextPacket, GitInfo, ProjectInfo, ToolsInfo
from aios.core.task import Task


def _make_context(language: str = "python") -> ContextPacket:
    ctx = ContextPacket()
    ctx.project = ProjectInfo(language=language, root="/tmp/test", name="test")
    ctx.tools = ToolsInfo(linter="ruff", formatter="ruff", test_runner="pytest")
    ctx.git = GitInfo(branch="main", status="clean")
    ctx.skills = ["project-dna", "coding-style"]
    return ctx


def _make_runtime(output: str) -> MagicMock:
    runtime = MagicMock()
    runtime.execute.return_value = output
    return runtime


def test_reviewer_capabilities():
    assert "ask_user" not in ReviewerAgent.required_capabilities
    assert "filesystem_write" not in ReviewerAgent.required_capabilities
    assert "filesystem_read" in ReviewerAgent.required_capabilities


def test_reviewer_execution_pass():
    runtime = _make_runtime('{"status": "pass", "feedback": "Code looks good."}')
    agent = ReviewerAgent(runtime)
    result = agent.execute(Task(description="review auth module"), _make_context())
    assert result.success is True
    assert '"status": "pass"' in result.output
    assert "Code looks good." in result.output


def test_reviewer_execution_fail():
    runtime = _make_runtime('{"status": "fail", "feedback": "Missing docstrings."}')
    agent = ReviewerAgent(runtime)
    result = agent.execute(Task(description="review auth module"), _make_context())
    assert result.success is True
    assert '"status": "fail"' in result.output
    assert "Missing docstrings." in result.output
