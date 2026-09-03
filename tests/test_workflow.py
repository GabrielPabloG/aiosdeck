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
from aios.agents.models import AgentResult
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

    src = repo / "src"
    src.mkdir()
    (src / "base.py").write_text("x = 1\n", encoding="utf-8")

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
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo, check=True)
    return repo


def _dev_runtime_writes(repo: Path, stub: str = "Implementation complete.") -> MagicMock:
    """A developer runtime that returns text AND writes a real file under src/."""
    runtime = MagicMock()

    def execute(*args, **kwargs):
        src = repo / "src"
        src.mkdir(parents=True, exist_ok=True)
        (src / "health_endpoint.py").write_text(
            'def health():\n    return "ok"\n',
            encoding="utf-8",
        )
        return stub

    runtime.execute.side_effect = execute
    return runtime


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
    dev_runtime = _dev_runtime_writes(repo)

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
    dev_runtime = _dev_runtime_writes(repo)

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


def test_developer_stage_carries_subtask_total(tmp_path):
    """Developer stage details include subtask_total for progress bars."""
    planner_runtime = MagicMock()
    planner_runtime.execute.return_value = json.dumps(VALID_PLAN)
    dev_runtime = MagicMock()
    dev_runtime.execute.return_value = "Implementation complete."

    workflow, scheduler = _make_workflow_no_optionals(tmp_path, planner_runtime, dev_runtime)
    try:
        result = workflow.execute(
            Task(description="Add endpoint /health"),
            _make_context(str(tmp_path)),
        )
    finally:
        scheduler.shutdown()

    assert result.success is True
    dev_stages = [s for s in result.stages if s.name.startswith("developer:")]
    assert len(dev_stages) == 2
    for s in dev_stages:
        assert s.details.get("subtask_total") == 2


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
    dev_runtime = _dev_runtime_writes(repo)

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


def test_is_implementation_task_true_for_code_types():
    """feat/fix/code are implementation tasks (they require a relevant diff)."""
    assert WorkflowEngine._is_implementation_task(Task(description="x", task_type="feat")) is True
    assert WorkflowEngine._is_implementation_task(Task(description="x", task_type="code")) is True


def test_is_implementation_task_false_for_docs_release_types():
    """docs/chore/release/meta are valid exceptions — not implementation."""
    for task_type in ("docs", "chore", "release", "meta"):
        assert (
            WorkflowEngine._is_implementation_task(Task(description="x", task_type=task_type))
            is False
        )


def test_is_implementation_task_defaults_to_code_when_type_missing():
    """An empty task_type falls back to 'code' and is treated as implementation."""
    assert WorkflowEngine._is_implementation_task(Task(description="x", task_type="")) is True


def _dev_runtime_noop(return_value: str = "No changes required.") -> MagicMock:
    """A developer runtime that claims success but writes nothing to disk."""
    runtime = MagicMock()
    runtime.execute.return_value = return_value
    return runtime


def test_workflow_noop_implementation_fails(tmp_path):
    """Regression (#79): an implementation task producing no src/ or tests/
    change must fail, not pass, even though the developer returned text."""
    repo = _setup_project(tmp_path)
    context = _make_context(str(repo))

    (repo / "docs").mkdir()
    (repo / "docs" / "changelog-fragment-20260101-000000.md").write_text(
        "# Changelog Fragment\n", encoding="utf-8"
    )
    (repo / "opencode.json").write_text('{"$schema": "opencode.json"}\n', encoding="utf-8")
    (repo / "TODO.md").write_text("- [ ] fix me\n", encoding="utf-8")

    planner_runtime = MagicMock()
    planner_runtime.execute.return_value = json.dumps(VALID_PLAN)
    dev_runtime = _dev_runtime_noop()

    workflow, scheduler, _ = _make_workflow(tmp_path, repo, planner_runtime, dev_runtime)
    try:
        result = workflow.execute(
            Task(description="Add endpoint /health", task_type="feat"), context
        )

        assert result.success is False
        assert any("no changes in src/ or tests/" in err for err in result.errors)
        assert result.changed_files == ()
        assert "developer:noop" in [s.name for s in result.stages]
        assert any(not s.success and s.name == "developer:noop" for s in result.stages)

        # DocumentationAgent must not create a new changelog, and git must not
        # commit anything as a successful implementation.
        seeded = {"changelog-fragment-20260101-000000.md"}
        actual = {p.name for p in (repo / "docs").glob("changelog-fragment-*.md")}
        assert actual == seeded
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


def test_workflow_pre_existing_dirty_tree_does_not_count_as_produced(tmp_path):
    """A pre-existing relevant change in src/ must NOT make a no-op task pass."""
    repo = _setup_project(tmp_path)
    context = _make_context(str(repo))

    src = repo / "src"
    (src / "existing.py").write_text("OLD\n", encoding="utf-8")

    planner_runtime = MagicMock()
    planner_runtime.execute.return_value = json.dumps(VALID_PLAN)
    dev_runtime = _dev_runtime_noop()

    workflow, scheduler, _ = _make_workflow(tmp_path, repo, planner_runtime, dev_runtime)
    try:
        result = workflow.execute(
            Task(description="Add endpoint /health", task_type="feat"), context
        )

        assert result.success is False
        assert any("no changes in src/ or tests/" in err for err in result.errors)
        assert result.changed_files == ()
    finally:
        scheduler.shutdown()


def test_workflow_pre_existing_dirty_plus_new_relevant_file_succeeds(tmp_path):
    """A no-op on src/existing.py but a NEW src/ file produced by the developer
    is a real change, so the task succeeds."""
    repo = _setup_project(tmp_path)
    context = _make_context(str(repo))

    src = repo / "src"
    (src / "existing.py").write_text("OLD\n", encoding="utf-8")

    planner_runtime = MagicMock()
    planner_runtime.execute.return_value = json.dumps(VALID_PLAN)
    dev_runtime = _dev_runtime_writes(repo)

    workflow, scheduler, _ = _make_workflow(tmp_path, repo, planner_runtime, dev_runtime)
    try:
        result = workflow.execute(
            Task(description="Add endpoint /health", task_type="feat"), context
        )

        assert result.success is True
        assert "src/health_endpoint.py" in result.changed_files
    finally:
        scheduler.shutdown()


def test_workflow_docs_task_without_code_change_succeeds(tmp_path):
    """A docs task changing only docs/ is a valid exception and must succeed."""
    repo = _setup_project(tmp_path)
    context = _make_context(str(repo))

    planner_runtime = MagicMock()
    planner_runtime.execute.return_value = json.dumps(
        {
            "goal": "Update docs",
            "subtasks": [
                {
                    "id": "1",
                    "description": "Document the endpoint",
                    "type": "documentation",
                    "priority": "low",
                    "dependencies": [],
                    "estimated_complexity": "low",
                }
            ],
            "risks": [],
            "unknowns": [],
        }
    )
    dev_runtime = _dev_runtime_noop()

    workflow, scheduler, _ = _make_workflow(tmp_path, repo, planner_runtime, dev_runtime)
    try:
        result = workflow.execute(Task(description="Update docs", task_type="docs"), context)

        assert result.success is True
        assert not any("no changes in src/ or tests/" in err for err in result.errors)
    finally:
        scheduler.shutdown()


class TestWorkflowEngineHelpers:
    """Unit tests for the pure helpers extracted from _run_developer_phase.

    They are @staticmethods, so they are exercised directly (no engine
    instance) to kill the ternary/set/any/f-string mutants cheaply.
    """

    def test_first_error_uses_first(self):
        result = AgentResult(success=False, errors=["error1", "error2"])
        assert WorkflowEngine._first_error(result, "fb") == "error1"

    def test_first_error_empty_uses_fallback(self):
        result = AgentResult(success=False, errors=[])
        assert WorkflowEngine._first_error(result, "Developer failed") == "Developer failed"

    def test_first_error_dual_fallbacks(self):
        result = AgentResult(success=False, errors=[])
        assert WorkflowEngine._first_error(result, "Developer failed") == "Developer failed"
        assert WorkflowEngine._first_error(result, "failed") == "failed"

    def test_subtask_type_present(self):
        assert WorkflowEngine._subtask_type({"type": "review"}) == "review"

    def test_subtask_type_defaults_to_code(self):
        assert WorkflowEngine._subtask_type({}) == "code"
        assert WorkflowEngine._subtask_type({"description": "x"}) == "code"

    def test_compute_produced_files_added(self):
        assert WorkflowEngine._compute_produced_files(
            ["a.py", "b.py"], ["a.py", "b.py", "c.py"]
        ) == ["c.py"]

    def test_compute_produced_files_deletions_ignored(self):
        assert (
            WorkflowEngine._compute_produced_files(["a.py", "b.py", "c.py"], ["a.py", "b.py"]) == []
        )

    def test_compute_produced_files_sorted_and_deduped(self):
        assert WorkflowEngine._compute_produced_files([], ["z.py", "a.py", "z.py", "m.py"]) == [
            "a.py",
            "m.py",
            "z.py",
        ]

    def test_compute_produced_files_empty_after(self):
        assert WorkflowEngine._compute_produced_files(["a.py"], []) == []

    def test_has_relevant_change_src(self):
        assert WorkflowEngine._has_relevant_change(["src/main.py"]) is True

    def test_has_relevant_change_tests(self):
        assert WorkflowEngine._has_relevant_change(["tests/test_main.py"]) is True

    def test_has_relevant_change_irrelevant(self):
        assert WorkflowEngine._has_relevant_change(["docs/readme.md"]) is False
        assert WorkflowEngine._has_relevant_change(["README.md"]) is False

    def test_has_relevant_change_empty(self):
        assert WorkflowEngine._has_relevant_change([]) is False

    def test_noop_reason_joins_files(self):
        reason = WorkflowEngine._noop_reason(["a.md", "b.txt"])
        assert "a.md, b.txt" in reason
        assert "Developer produced no changes in src/ or tests/ (no-op)" in reason
        assert "changed files:" in reason

    def test_noop_reason_empty_uses_none(self):
        reason = WorkflowEngine._noop_reason([])
        assert "none" in reason
        assert "no-op" in reason


def test_workflow_noop_implementation_with_irrelevant_new_file(tmp_path):
    """Developer adds a NEW file, but only under docs/ -> produced is non-empty
    yet not relevant -> no-op failure. Exercises the comma-joined _noop_reason
    branch and the `if ctx.cards` True path."""
    repo = _setup_project(tmp_path)
    context = _make_context(str(repo))

    planner_runtime = MagicMock()
    planner_runtime.execute.return_value = json.dumps(VALID_PLAN)
    dev_runtime = MagicMock()

    def _dev(*_a, **_k):
        # A new file at the repo root (a tracked directory) reports individually,
        # not collapsed into a directory entry, and is not under src/ or tests/.
        (repo / "notes.txt").write_text("scratch\n", encoding="utf-8")
        return "docs only"

    dev_runtime.execute.side_effect = _dev

    workflow, scheduler, _ = _make_workflow(tmp_path, repo, planner_runtime, dev_runtime)
    try:
        result = workflow.execute(
            Task(description="Add endpoint /health", task_type="feat"), context
        )

        assert result.success is False
        assert result.changed_files == ("notes.txt",)
        assert any("no-op" in err and "notes.txt" in err for err in result.errors)
    finally:
        scheduler.shutdown()


def test_workflow_noop_empty_subtasks(tmp_path):
    """Zero subtasks: nothing produced and no cards exist, so the no-op path
    must not touch a card (the `if ctx.cards` False branch)."""
    repo = _setup_project(tmp_path)
    context = _make_context(str(repo))

    planner_runtime = MagicMock()
    planner_runtime.execute.return_value = json.dumps(
        {"goal": "g", "subtasks": [], "risks": [], "unknowns": []}
    )
    dev_runtime = _dev_runtime_noop()

    workflow, scheduler, _ = _make_workflow(tmp_path, repo, planner_runtime, dev_runtime)
    try:
        result = workflow.execute(Task(description="g", task_type="feat"), context)

        assert result.success is False
        assert result.changed_files == ()
        assert any("no-op" in err for err in result.errors)
    finally:
        scheduler.shutdown()
