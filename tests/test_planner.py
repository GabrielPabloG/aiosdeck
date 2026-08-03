"""Tests for PlannerAgent — planning prompt, JSON parsing, execution."""

from unittest.mock import MagicMock

from aios.agents.planner import PlannerAgent
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


def test_planner_returns_success_with_valid_json():
    runtime = _make_runtime('{"goal":"test","subtasks":[],"risks":[],"unknowns":[]}')
    agent = PlannerAgent(runtime)
    result = agent.execute(Task(description="do something"), _make_context())
    assert result.success is True
    assert "subtasks" in result.output


def test_planner_extracts_json_from_markdown():
    raw = (
        "Here is the plan:\n```json\n"
        '{"goal":"test","subtasks":[],"risks":[],"unknowns":[]}\n'
        "```\nGood luck!"
    )
    runtime = _make_runtime(raw)
    agent = PlannerAgent(runtime)
    result = agent.execute(Task(description="do something"), _make_context())
    assert result.success is True
    assert "subtasks" in result.output


def test_planner_extracts_json_from_text_wrapper():
    raw = (
        "Sure! Let me plan that.\n\n"
        '{"goal":"auth","subtasks":[{'
        '"id":"1","type":"code","description":"Add lib",'
        '"priority":"high","dependencies":[],'
        '"estimated_complexity":"low"}],'
        '"risks":[],"unknowns":[]}\n\n'
        "Hope this helps."
    )
    runtime = _make_runtime(raw)
    agent = PlannerAgent(runtime)
    result = agent.execute(Task(description="add auth"), _make_context())
    assert result.success is True


def test_planner_fails_on_no_json():
    runtime = _make_runtime("Just some text without any JSON object at all.")
    agent = PlannerAgent(runtime)
    result = agent.execute(Task(description="do something"), _make_context())
    assert result.success is False
    assert "no json" in result.errors[0].lower()


def test_planner_fails_on_invalid_json():
    runtime = _make_runtime('{"goal":"broken", "subtasks": [invalid]}')
    agent = PlannerAgent(runtime)
    result = agent.execute(Task(description="do something"), _make_context())
    assert result.success is False
    assert "invalid json" in result.errors[0].lower()


def test_planner_fails_on_missing_subtasks():
    runtime = _make_runtime('{"goal":"test","risks":[]}')
    agent = PlannerAgent(runtime)
    result = agent.execute(Task(description="do something"), _make_context())
    assert result.success is False
    assert "subtasks" in result.errors[0].lower()


def test_planner_handles_runtime_error():
    runtime = _make_runtime("")
    runtime.execute.side_effect = RuntimeError("connection lost")
    agent = PlannerAgent(runtime)
    result = agent.execute(Task(description="do something"), _make_context())
    assert result.success is False
    assert "connection lost" in result.errors[0]
