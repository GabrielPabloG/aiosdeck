"""Integration tests — every agent executes through the AgentExecutor boundary.

Validates, for all seven agents: execution via the executor, emission of the
standardized agent.* lifecycle events, and capability enforcement.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aios.agents.contracts import PERMISSION_DENIED, AgentTask
from aios.agents.developer import DeveloperAgent
from aios.agents.documentation import DocumentationAgent
from aios.agents.executor import AgentExecutor, make_request
from aios.agents.git import GitAgent
from aios.agents.models import AgentResult
from aios.agents.planner import PlannerAgent
from aios.agents.research import ResearchAgent
from aios.agents.reviewer import ReviewerAgent
from aios.agents.tester import TesterAgent
from aios.context.packet import ContextPacket, GitInfo, ProjectInfo, ToolsInfo
from aios.events.bus import EventBus
from aios.events.events import (
    AGENT_EXECUTION_COMPLETED,
    AGENT_EXECUTION_STARTED,
    AGENT_LIFECYCLE_CHANGED,
)
from aios.security.capabilities import CapabilityEnforcer
from tests.agent_compliance_matrix import AGENT_COMPLIANCE_MATRIX, AGENT_NAMES

FIXTURE = Path(__file__).parent.parent / "fixtures" / "simple_repo"
TEST_FIXTURE = Path(__file__).parent.parent / "fixtures" / "test_project"

VALID_PLAN = json.dumps({"goal": "g", "subtasks": [], "risks": [], "unknowns": []})

SAMPLE_REPORT = {
    "summary": {"passed": 1},
    "items": [{"severity": "warning", "file": "a.py", "line": 1, "message": "todo"}],
}


def _context() -> ContextPacket:
    ctx = ContextPacket()
    ctx.project = ProjectInfo(language="python", root="/tmp", name="test")
    ctx.tools = ToolsInfo(linter="ruff", formatter="ruff", test_runner="pytest")
    ctx.git = GitInfo(branch="main", status="clean")
    ctx.skills = ["project-dna", "coding-style"]
    return ctx


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "file.txt").write_text("hello\n", encoding="utf-8")
    return repo


def _agent_and_task(name: str, tmp_path: Path):  # noqa: PLR0911 - one branch per agent
    if name == "planner":
        runtime = MagicMock()
        runtime.execute.return_value = VALID_PLAN
        return (
            PlannerAgent(runtime),
            AgentTask(description="plan something", task_type="plan"),
            _context(),
        )
    if name == "developer":
        runtime = MagicMock()
        runtime.execute.return_value = "implementation complete"
        return DeveloperAgent(runtime), AgentTask(description="implement feature"), _context()
    if name == "research":
        return ResearchAgent(), AgentTask(description="auth flow", params={"scope": "web"}), None
    if name == "reviewer":
        return (
            ReviewerAgent(),
            AgentTask(
                description="review", params={"target": str(FIXTURE), "level": "conventions"}
            ),
            None,
        )
    if name == "tester":
        return (
            TesterAgent(),
            AgentTask(
                description="run tests",
                params={"target": str(TEST_FIXTURE), "dry_run": True},
            ),
            None,
        )
    if name == "documentation":
        return (
            DocumentationAgent(),
            AgentTask(description="fragment", params={"report": SAMPLE_REPORT, "dry_run": True}),
            None,
        )
    if name == "git":
        repo = _init_repo(tmp_path)
        return (
            GitAgent(repository=repo),
            AgentTask(description="stage changes", task_type="stage"),
            None,
        )
    raise KeyError(name)


@pytest.mark.parametrize("name", AGENT_NAMES)
def test_agent_executes_via_executor_and_emits_events(name, tmp_path):
    agent, task, context = _agent_and_task(name, tmp_path)
    bus = EventBus()
    received: list = []
    bus.subscribe("agent.*", received.append)

    outcome = AgentExecutor(event_bus=bus).execute(make_request(agent, task, context))

    assert outcome.status == "succeeded"
    assert isinstance(outcome.result, AgentResult)
    assert outcome.result.success is True
    assert outcome.result.agent == name
    assert outcome.result.task_id == task.task_id
    assert outcome.duration_ms >= 0

    topics = {event.topic for event in received}
    assert AGENT_EXECUTION_STARTED in topics
    assert AGENT_EXECUTION_COMPLETED in topics
    assert AGENT_LIFECYCLE_CHANGED in topics


@pytest.mark.parametrize("name", AGENT_NAMES)
def test_agent_result_adheres_to_contract(name, tmp_path):
    agent, task, context = _agent_and_task(name, tmp_path)
    outcome = AgentExecutor().execute(make_request(agent, task, context))
    result = outcome.result
    assert isinstance(result, AgentResult)
    assert isinstance(result.output, str)
    assert isinstance(result.errors, list)
    assert result.status == "succeeded"


@pytest.mark.parametrize("name", AGENT_NAMES)
def test_agent_passes_canonical_capability_enforcement(name, tmp_path):
    agent, _task, _context = _agent_and_task(name, tmp_path)
    CapabilityEnforcer().validate(agent)


def test_capability_violation_is_permission_denied(tmp_path):
    class OverprivilegedReviewer(ReviewerAgent):
        required_capabilities = ["filesystem_read", "shell"]

    agent = OverprivilegedReviewer()
    task = AgentTask(description="review", params={"target": str(FIXTURE)})

    executor = AgentExecutor(capabilities_enforcer=CapabilityEnforcer())
    outcome = executor.execute(make_request(agent, task))
    assert outcome.status == "failed"
    assert outcome.error is not None
    assert outcome.error.code == PERMISSION_DENIED


def test_read_only_agents_never_declare_privileged_capabilities():
    for name in ("planner", "research", "reviewer"):
        spec = AGENT_COMPLIANCE_MATRIX[name]
        privileged = {"shell", "git", "internet", "filesystem_write"}
        assert not (set(spec["capabilities"]) & privileged), f"{name} is not read-only"
