"""Tests for DeveloperAgent — context, skills, prompt, runtime interaction."""

from unittest.mock import MagicMock

from aios.agents import AgentResult, Task
from aios.agents.developer import DeveloperAgent
from aios.context.packet import ContextPacket, ProjectInfo, ToolsInfo


def _make_context(language: str = "python") -> ContextPacket:
    ctx = ContextPacket()
    ctx.project = ProjectInfo(language=language, root="/tmp/test", name="test")
    ctx.tools = ToolsInfo(linter="ruff", formatter="ruff", test_runner="pytest")
    ctx.skills = ["project-dna", "coding-style"]
    return ctx


def _make_runtime(return_value: str | None = None) -> MagicMock:
    runtime = MagicMock()
    runtime.execute.return_value = return_value or "[output from runtime]"
    return runtime


def test_agent_returns_result():
    runtime = _make_runtime()
    agent = DeveloperAgent(runtime)
    task = Task(description="Write a hello world function")
    result = agent.execute(task, _make_context())
    assert isinstance(result, AgentResult)
    assert result.success is True
    assert len(result.output) > 0


def test_agent_calls_runtime_once():
    runtime = _make_runtime()
    agent = DeveloperAgent(runtime)
    task = Task(description="Write a test")
    agent.execute(task, _make_context())
    runtime.execute.assert_called_once()


def test_agent_prompt_contains_task_description():
    runtime = _make_runtime()
    agent = DeveloperAgent(runtime)
    task = Task(description="Implement OAuth2 login")
    agent.execute(task, _make_context())
    call_args = runtime.execute.call_args
    prompt = call_args[0][0]
    assert "Implement OAuth2 login" in prompt


def test_agent_prompt_contains_context():
    runtime = _make_runtime()
    agent = DeveloperAgent(runtime)
    agent.execute(Task(description="test"), _make_context(language="python"))
    prompt = runtime.execute.call_args[0][0]
    assert "python" in prompt
    assert "ruff" in prompt
    assert "pytest" in prompt


def test_agent_prompt_contains_skills():
    runtime = _make_runtime()
    agent = DeveloperAgent(runtime)
    agent.execute(Task(description="test"), _make_context())
    skills_arg = runtime.execute.call_args[0][1]
    assert "project-dna" in skills_arg
    assert "coding-style" in skills_arg


def test_agent_with_python_project():
    runtime = _make_runtime()
    agent = DeveloperAgent(runtime)
    ctx = _make_context(language="python")
    ctx.tools.linter = "ruff"
    ctx.tools.formatter = "black"
    ctx.tools.test_runner = "pytest"
    agent.execute(Task(description="Add type hints"), ctx)
    prompt = runtime.execute.call_args[0][0]
    assert "python" in prompt
    assert "ruff" in prompt
    assert "black" in prompt
    assert "pytest" in prompt
    assert "Add type hints" in prompt


def test_agent_handles_runtime_error():
    runtime = _make_runtime()
    runtime.execute.side_effect = RuntimeError("connection lost")
    agent = DeveloperAgent(runtime)
    result = agent.execute(Task(description="test"), _make_context())
    assert result.success is False
    assert len(result.errors) > 0
    assert "connection lost" in result.errors[0]
