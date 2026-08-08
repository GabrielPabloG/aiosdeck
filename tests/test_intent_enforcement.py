"""Tests for intent enforcement at the executor boundary.

The intent run-gate is opt-in: ``intent=None`` is byte-identical to previous
behavior. When an intent is present, the effective permissions are
``(intent.actions - intent.deny) ∩ expand(agent.capabilities)`` — an empty
effective set is a structured ``PERMISSION_DENIED`` (never a silent fallback),
and an intent can never elevate an agent's coarse capabilities.
"""

import json
from unittest.mock import MagicMock

from aios.agents.contracts import (
    PERMISSION_DENIED,
    STATE_FAILED,
    STATE_SUCCEEDED,
    AgentCapabilities,
    AgentMetadata,
    AgentTask,
    RetryPolicy,
)
from aios.agents.executor import AgentExecutor, make_request
from aios.agents.models import AgentResult
from aios.context.packet import ContextPacket, GitInfo, ProjectInfo, ToolsInfo
from aios.core.task import Task
from aios.security import IntentPolicy, effective_permissions
from aios.security.actions import (
    ASK_USER_ACTION,
    FILESYSTEM_READ_ACTION,
    GIT_BRANCH,
    GIT_COMMIT,
    NETWORK_ACCESS,
    SHELL_EXECUTE,
    WORKFLOW_INTENT,
)


class _Agent:
    def __init__(self, name: str, capabilities: list[str], fn=None):
        self.name = name
        self._fn = fn or (lambda task, context: AgentResult(success=True, output="ok"))
        self.metadata = AgentMetadata(
            name=name,
            timeout=None,
            retry_policy=RetryPolicy(),
        )
        self.capabilities = AgentCapabilities.from_list(capabilities)

    def execute(self, task, context):
        return self._fn(task, context)


def _task() -> AgentTask:
    return AgentTask(description="do something")


def test_intent_none_is_unchanged():
    executor = AgentExecutor()
    request = make_request(_Agent("fake", ["filesystem_read"]), _task())
    assert request.intent is None
    outcome = executor.execute(request)
    assert outcome.status == STATE_SUCCEEDED
    assert outcome.result.success is True


def test_git_agent_under_read_only_intent_is_denied():
    intent = IntentPolicy(
        name="review",
        actions=frozenset({FILESYSTEM_READ_ACTION}),
    )
    executor = AgentExecutor()
    outcome = executor.execute(make_request(_Agent("git", ["git"]), _task(), intent=intent))
    assert outcome.status == STATE_FAILED
    assert outcome.error is not None
    assert outcome.error.code == PERMISSION_DENIED
    assert GIT_BRANCH in outcome.error.message
    assert GIT_COMMIT in outcome.error.message


def test_intent_overlap_runs_and_attaches_intent_to_context():
    context = ContextPacket()
    intent = IntentPolicy(actions=frozenset({GIT_BRANCH, GIT_COMMIT}))
    executor = AgentExecutor()
    outcome = executor.execute(
        make_request(_Agent("git", ["git"]), _task(), context=context, intent=intent)
    )
    assert outcome.status == STATE_SUCCEEDED
    assert context.intent is intent


def test_explicit_deny_removes_only_overlap_and_denies():
    intent = IntentPolicy(
        actions=frozenset({GIT_BRANCH}),
        deny=frozenset({GIT_BRANCH}),
    )
    executor = AgentExecutor()
    outcome = executor.execute(make_request(_Agent("git", ["git"]), _task(), intent=intent))
    assert outcome.status == STATE_FAILED
    assert outcome.error is not None
    assert outcome.error.code == PERMISSION_DENIED


def test_deny_removes_action_but_other_overlap_remains():
    intent = IntentPolicy(
        actions=frozenset({GIT_BRANCH, GIT_COMMIT}),
        deny=frozenset({GIT_COMMIT}),
    )
    executor = AgentExecutor()
    outcome = executor.execute(make_request(_Agent("git", ["git"]), _task(), intent=intent))
    assert outcome.status == STATE_SUCCEEDED


def test_permissive_intent_cannot_elevate_capabilities():
    intent = IntentPolicy(
        actions=frozenset({NETWORK_ACCESS, SHELL_EXECUTE, FILESYSTEM_READ_ACTION})
    )
    reader = _Agent("reader", ["filesystem_read"])
    effective = effective_permissions(intent, reader.capabilities)
    assert effective == frozenset({FILESYSTEM_READ_ACTION})
    assert NETWORK_ACCESS not in effective
    assert SHELL_EXECUTE not in effective


def test_workflow_intent_extends_develop_with_ask_user():
    assert WORKFLOW_INTENT.name == "develop"
    assert ASK_USER_ACTION in WORKFLOW_INTENT.actions
    assert FILESYSTEM_READ_ACTION in WORKFLOW_INTENT.actions


def test_workflow_restricted_intent_blocks_developer(tmp_path):
    repo = _setup_project(tmp_path)
    context = _make_context(str(repo))
    context.intent = IntentPolicy(name="restricted", actions=frozenset({ASK_USER_ACTION}))

    planner_runtime = MagicMock()
    planner_runtime.execute.return_value = json.dumps(VALID_PLAN)
    dev_runtime = MagicMock()
    dev_runtime.execute.return_value = "Implementation complete."

    workflow = _make_workflow(tmp_path, repo, planner_runtime, dev_runtime)
    result = workflow.execute(Task(description="Add endpoint /health"), context)

    assert result.success is False
    assert any(stage.name == "developer:1" and not stage.success for stage in result.stages)
    assert any("grants no action" in (error or "") for error in result.errors)


def test_workflow_default_intent_passes_and_sets_context(tmp_path):
    repo = _setup_project(tmp_path)
    context = _make_context(str(repo))
    planner_runtime = MagicMock()
    planner_runtime.execute.return_value = json.dumps(VALID_PLAN)
    dev_runtime = MagicMock()
    dev_runtime.execute.return_value = "Implementation complete."

    workflow = _make_workflow(tmp_path, repo, planner_runtime, dev_runtime)
    workflow._agents["git"].push = MagicMock()
    result = workflow.execute(Task(description="Add endpoint /health"), context)

    assert result.success is True
    assert context.intent is WORKFLOW_INTENT
    assert WORKFLOW_INTENT.actions >= effective_permissions(
        WORKFLOW_INTENT, workflow._agents["developer"].capabilities
    )


VALID_PLAN = {
    "goal": "Add endpoint /health",
    "subtasks": [
        {"id": "1", "description": "Create /health route handler", "type": "code"},
        {"id": "2", "description": "Add tests for /health endpoint", "type": "test"},
    ],
    "risks": [],
    "unknowns": [],
}


def _make_context(root: str) -> ContextPacket:
    ctx = ContextPacket()
    ctx.project = ProjectInfo(language="python", root=root, name="test")
    ctx.tools = ToolsInfo(linter="ruff", formatter="ruff", test_runner="pytest")
    ctx.git = GitInfo(branch="main", status="clean")
    ctx.skills = ["project-dna", "coding-style"]
    return ctx


def _setup_project(tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "health.py").write_text(
        '"""Health endpoint module."""\ndef health_check():\n    return {\'status\': \'ok\'}\n',
        encoding="utf-8",
    )
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_health.py").write_text(
        "def test_health_check():\n    assert True\n",
        encoding="utf-8",
    )
    return repo


def _make_workflow(tmp_path, repo, planner_runtime, dev_runtime):
    from aios.agents.developer import DeveloperAgent
    from aios.agents.documentation import DocumentationAgent
    from aios.agents.git import GitAgent
    from aios.agents.planner import PlannerAgent
    from aios.agents.reviewer import ReviewerAgent
    from aios.agents.tester import TesterAgent
    from aios.scheduler import KanbanEngine
    from aios.workflow import WorkflowEngine

    scheduler = KanbanEngine(project_path=repo, db_path=str(tmp_path / "kanban.db"))
    scheduler.initialize()
    git = GitAgent(repository=repo)
    executor = AgentExecutor()
    workflow = WorkflowEngine(
        planner=PlannerAgent(planner_runtime),
        scheduler=scheduler,
        developer=DeveloperAgent(dev_runtime),
        reviewer=ReviewerAgent(),
        tester=TesterAgent(),
        documentation=DocumentationAgent(docs_dir=str(repo / "docs")),
        git=git,
        project_path=repo,
        executor=executor,
    )
    return workflow
