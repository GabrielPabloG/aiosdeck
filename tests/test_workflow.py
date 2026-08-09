"""Tests for WorkflowEngine — linear orchestration of the agent pipeline."""

import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aios.agents.developer import DeveloperAgent
from aios.agents.documentation import DocumentationAgent
from aios.agents.executor import AgentExecutor
from aios.agents.git import GitAgent
from aios.agents.planner import PlannerAgent
from aios.agents.research import ResearchAgent
from aios.agents.reviewer import ReviewerAgent
from aios.agents.tester import TesterAgent
from aios.context.packet import ContextPacket, GitInfo, ProjectInfo, ToolsInfo
from aios.core.task import Task
from aios.scheduler import KanbanEngine
from aios.workflow import WorkflowConfigurationError, WorkflowEngine, WorkflowHealth

VALID_PLAN = {
    "goal": "Add endpoint /health",
    "subtasks": [
        {
            "id": "1",
            "description": "Create /health route handler",
            "type": "code",
            "priority": "high",
            "dependencies": [],
            "estimated_complexity": "low",
        },
        {
            "id": "2",
            "description": "Add tests for /health endpoint",
            "type": "test",
            "priority": "high",
            "dependencies": ["1"],
            "estimated_complexity": "low",
        },
    ],
    "risks": ["Breaking existing routes"],
    "unknowns": ["Framework version"],
}

STAGE_NAMES = [
    "planner",
    "git",  # create_branch
    "scheduler",
    "developer:1",
    "developer:2",
    "reviewer",
    "tester",
    "documentation",
    "git",  # stage + commit
]


def _make_context(root: str) -> ContextPacket:
    ctx = ContextPacket()
    ctx.project = ProjectInfo(language="python", root=root, name="test")
    ctx.tools = ToolsInfo(linter="ruff", formatter="ruff", test_runner="pytest")
    ctx.git = GitInfo(branch="main", status="clean")
    ctx.skills = ["project-dna", "coding-style"]
    return ctx


def _setup_project(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)

    (repo / "health.py").write_text(
        '"""Health endpoint module."""\n'
        "def health_check():\n"
        "    # TODO: add error handling\n"
        '    return {"status": "ok"}\n',
        encoding="utf-8",
    )

    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_health.py").write_text(
        "def test_health_check():\n    assert True\n",
        encoding="utf-8",
    )
    return repo


def _make_workflow(
    tmp_path: Path,
    repo: Path,
    planner_runtime: MagicMock | None = None,
    dev_runtime: MagicMock | None = None,
    researcher: "ResearchAgent | None" = None,
) -> tuple[WorkflowEngine, KanbanEngine, GitAgent]:
    scheduler = KanbanEngine(project_path=repo, db_path=str(tmp_path / "kanban.db"))
    scheduler.initialize()
    git = GitAgent(repository=repo)
    executor = AgentExecutor()
    workflow = WorkflowEngine(
        planner=PlannerAgent(planner_runtime or MagicMock()),
        scheduler=scheduler,
        developer=DeveloperAgent(dev_runtime or MagicMock()),
        reviewer=ReviewerAgent(),
        researcher=researcher,
        tester=TesterAgent(),
        documentation=DocumentationAgent(docs_dir=str(repo / "docs")),
        git=git,
        project_path=repo,
        executor=executor,
    )
    return workflow, scheduler, git


def test_workflow_full_pipeline_succeeds(tmp_path):
    repo = _setup_project(tmp_path)
    context = _make_context(str(repo))

    planner_runtime = MagicMock()
    planner_runtime.execute.return_value = json.dumps(VALID_PLAN)
    dev_runtime = MagicMock()
    dev_runtime.execute.return_value = "Implementation complete."

    workflow, scheduler, git = _make_workflow(tmp_path, repo, planner_runtime, dev_runtime)
    git.push = MagicMock()
    try:
        result = workflow.execute(Task(description="Add endpoint /health"), context)

        assert result.success is True
        assert result.run_id == 1
        assert result.branch == "feature/add-endpoint-health-1"
        assert len(result.stages) == len(STAGE_NAMES)
        assert [s.name for s in result.stages] == STAGE_NAMES
        assert result.subtask_count == len(VALID_PLAN["subtasks"])
        assert result.completed_count == len(VALID_PLAN["subtasks"])
        assert result.errors == ()
        assert result.finished_at is not None
        assert json.dumps(asdict(result))

        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        assert branch.stdout.strip() == "feature/add-endpoint-health-1"

        log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        assert "feat: Add endpoint /health" in log.stdout

        git.push.assert_not_called()
    finally:
        scheduler.shutdown()


def test_workflow_planner_failure_stops(tmp_path):
    repo = _setup_project(tmp_path)
    context = _make_context(str(repo))

    planner_runtime = MagicMock()
    planner_runtime.execute.return_value = "no valid json here"

    workflow, scheduler, _ = _make_workflow(tmp_path, repo, planner_runtime=planner_runtime)
    try:
        result = workflow.execute(Task(description="Add endpoint /health"), context)

        assert result.success is False
        assert [s.name for s in result.stages] == ["planner"]
        assert result.branch is None
        assert result.plan is None
        assert result.errors

        assert scheduler.list_boards() == []

        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        assert "feature/" not in branch.stdout
    finally:
        scheduler.shutdown()


def test_workflow_developer_failure_stops(tmp_path):
    repo = _setup_project(tmp_path)
    context = _make_context(str(repo))

    planner_runtime = MagicMock()
    planner_runtime.execute.return_value = json.dumps(VALID_PLAN)
    dev_runtime = MagicMock()
    dev_runtime.execute.side_effect = RuntimeError("execution failed")

    workflow, scheduler, _ = _make_workflow(tmp_path, repo, planner_runtime, dev_runtime)
    try:
        result = workflow.execute(Task(description="Add endpoint /health"), context)

        assert result.success is False
        assert [s.name for s in result.stages] == [
            "planner",
            "git",
            "scheduler",
            "developer:1",
        ]
        assert result.completed_count == 0

        assert dev_runtime.execute.call_count == 1

        board = scheduler.list_boards()[0]
        cards = scheduler.list_cards(board.id)
        assert len(cards) == len(VALID_PLAN["subtasks"])
        assert cards[0].blocked is True
        assert cards[1].column == "Backlog"
    finally:
        scheduler.shutdown()


def test_workflow_tester_failure_stops(tmp_path):
    repo = _setup_project(tmp_path)
    context = _make_context(str(repo))

    (repo / "tests" / "test_fail.py").write_text(
        "def test_fails():\n    assert False\n",
        encoding="utf-8",
    )

    planner_runtime = MagicMock()
    planner_runtime.execute.return_value = json.dumps(VALID_PLAN)
    dev_runtime = MagicMock()
    dev_runtime.execute.return_value = "Implementation complete."

    workflow, scheduler, _ = _make_workflow(tmp_path, repo, planner_runtime, dev_runtime)
    try:
        result = workflow.execute(Task(description="Add endpoint /health"), context)

        assert result.success is False
        assert [s.name for s in result.stages] == [
            "planner",
            "git",
            "scheduler",
            "developer:1",
            "developer:2",
            "reviewer",
            "tester",
        ]
        assert result.branch == "feature/add-endpoint-health-1"

        assert not list((repo / "docs").glob("changelog-fragment-*.md"))

        log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        assert "feat:" not in log.stdout
    finally:
        scheduler.shutdown()


def test_workflow_health_check(tmp_path):
    repo = _setup_project(tmp_path)

    workflow, scheduler, _ = _make_workflow(tmp_path, repo)
    try:
        health = workflow.health_check()

        assert isinstance(health, WorkflowHealth)
        assert health.healthy is True
        assert health.missing_agents == []
        assert set(health.agents) == {
            "planner",
            "scheduler",
            "developer",
            "reviewer",
            "research",
            "tester",
            "documentation",
            "git",
        }
    finally:
        scheduler.shutdown()


def test_workflow_configuration_error_on_missing_agent(tmp_path):
    repo = tmp_path

    with pytest.raises(WorkflowConfigurationError):
        WorkflowEngine(
            planner=None,
            scheduler=KanbanEngine(project_path=repo),
            developer=DeveloperAgent(MagicMock()),
            reviewer=ReviewerAgent(),
            tester=TesterAgent(),
            documentation=DocumentationAgent(),
            git=GitAgent(repository=repo),
            executor=AgentExecutor(),
        )


def _make_workflow_no_optionals(
    tmp_path: Path,
    planner_runtime: MagicMock | None = None,
    dev_runtime: MagicMock | None = None,
) -> tuple[WorkflowEngine, KanbanEngine]:
    scheduler = KanbanEngine(project_path=tmp_path, db_path=str(tmp_path / "kanban.db"))
    scheduler.initialize()
    workflow = WorkflowEngine(
        planner=PlannerAgent(planner_runtime or MagicMock()),
        scheduler=scheduler,
        developer=DeveloperAgent(dev_runtime or MagicMock()),
        reviewer=ReviewerAgent(),
        project_path=tmp_path,
        executor=AgentExecutor(),
    )
    return workflow, scheduler


def test_workflow_optional_agents_skipped(tmp_path):
    """Without tester/documentation/git the pipeline skips their stages gracefully."""
    planner_runtime = MagicMock()
    planner_runtime.execute.return_value = json.dumps(VALID_PLAN)
    dev_runtime = MagicMock()
    dev_runtime.execute.return_value = "Implementation complete."

    workflow, scheduler = _make_workflow_no_optionals(tmp_path, planner_runtime, dev_runtime)
    try:
        result = workflow.execute(
            Task(description="Add endpoint /health"), _make_context(str(tmp_path))
        )

        assert result.success is True
        assert result.branch is None
        assert [s.name for s in result.stages] == [
            "planner",
            "git",
            "scheduler",
            "developer:1",
            "developer:2",
            "reviewer",
            "tester",
            "documentation",
            "git",
        ]
        skipped = [s for s in result.stages if s.details.get("skipped")]
        assert [s.name for s in skipped] == ["git", "tester", "documentation", "git"]
    finally:
        scheduler.shutdown()


def test_workflow_on_stage_callback(tmp_path):
    """on_stage receives every stage as the pipeline progresses."""
    planner_runtime = MagicMock()
    planner_runtime.execute.return_value = json.dumps(VALID_PLAN)
    dev_runtime = MagicMock()
    dev_runtime.execute.return_value = "Implementation complete."

    workflow, scheduler = _make_workflow_no_optionals(tmp_path, planner_runtime, dev_runtime)
    received: list = []
    try:
        result = workflow.execute(
            Task(description="Add endpoint /health"),
            _make_context(str(tmp_path)),
            on_stage=received.append,
        )
    finally:
        scheduler.shutdown()

    assert result.success is True
    assert [s.name for s in received] == [s.name for s in result.stages]


def test_workflow_health_with_missing_optionals(tmp_path):
    """Missing optional agents do not make the pipeline unhealthy."""
    workflow, scheduler = _make_workflow_no_optionals(tmp_path)
    try:
        health = workflow.health_check()

        assert health.healthy is True
        assert health.missing_agents == []
        assert set(health.optional) == {"tester", "documentation", "git", "research"}
        assert health.agents["git"] is False
        assert health.agents["research"] is False
    finally:
        scheduler.shutdown()


def test_workflow_research_front_gate_feeds_planner(tmp_path):
    """With a researcher injected, research runs first and feeds the planner."""
    repo = _setup_project(tmp_path)
    context = _make_context(str(repo))

    planner_runtime = MagicMock()
    planner_runtime.execute.return_value = json.dumps(VALID_PLAN)
    dev_runtime = MagicMock()
    dev_runtime.execute.return_value = "Implementation complete."

    workflow, scheduler, _ = _make_workflow(
        tmp_path,
        repo,
        planner_runtime=planner_runtime,
        dev_runtime=dev_runtime,
        researcher=ResearchAgent(),
    )
    try:
        result = workflow.execute(Task(description="Add endpoint /health"), context)

        assert result.success is True
        assert result.stages[0].name == "research"
        assert result.stages[0].success is True
        assert result.research_result is not None
        assert result.research_result["status"] in ("ok", "partial")

        prompt = planner_runtime.execute.call_args[0][0]
        assert "## Research" in prompt
    finally:
        scheduler.shutdown()


def test_build_branch_truncates_long_goal():
    """A huge goal must not overflow git's 255-char refname limit."""
    huge = "Implement " + "long-" * 100 + "goal"
    branch = WorkflowEngine._build_branch(42, huge)
    assert len(branch) < 255
    assert branch.startswith("feature/")
    assert branch.endswith("-42")


def test_build_branch_run_id_keeps_uniqueness():
    """Different runs of the same goal still produce distinct branches."""
    goal = "Fix " + "b" * 200
    assert WorkflowEngine._build_branch(1, goal) != WorkflowEngine._build_branch(2, goal)


def test_build_branch_short_goal_unchanged():
    assert (
        WorkflowEngine._build_branch(1, "Add endpoint /health") == "feature/add-endpoint-health-1"
    )


def test_build_branch_goal_without_words():
    assert WorkflowEngine._build_branch(7, "!!!") == "feature/task-7"
