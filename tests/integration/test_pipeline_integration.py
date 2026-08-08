"""
Integration tests for the v0.9 agent pipeline.

These tests validate that independently developed agents can
cooperate through their public APIs before the Workflow Engine
is introduced.

They intentionally exercise only public interfaces.
"""

import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from unittest.mock import MagicMock

from aios.agents.developer import DeveloperAgent
from aios.agents.documentation import DocumentationAgent
from aios.agents.git import GitAgent
from aios.agents.planner import PlannerAgent
from aios.agents.reviewer import ReviewerAgent
from aios.agents.tester import TesterAgent
from aios.context.packet import ContextPacket, GitInfo, ProjectInfo, ToolsInfo
from aios.core.task import Task
from aios.scheduler import KanbanEngine

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


def test_pipeline_a_planner_to_scheduler(tmp_path):
    """Planner produces a plan that the Scheduler can consume."""
    repo = _setup_project(tmp_path)
    context = _make_context(str(repo))

    runtime = MagicMock()
    runtime.execute.return_value = json.dumps(VALID_PLAN)
    planner = PlannerAgent(runtime)

    plan_result = planner.execute(Task(description="Add endpoint /health"), context)

    assert plan_result.success is True
    plan = json.loads(plan_result.output)
    assert plan["subtasks"]
    assert "risks" in plan

    scheduler = KanbanEngine(project_path=repo, db_path=str(tmp_path / "kanban.db"))
    scheduler.initialize()
    try:
        board = scheduler.create_board(plan["goal"])
        assert board.id is not None

        for subtask in plan["subtasks"]:
            scheduler.create_card(board.id, subtask["description"])

        cards = scheduler.list_cards(board.id)
        assert len(cards) == len(plan["subtasks"])
        assert all(card.column == "Backlog" for card in cards)
    finally:
        scheduler.shutdown()


def test_pipeline_b_developer_to_git(tmp_path):
    """Developer → Reviewer → Tester → Documentation → Git cooperate end-to-end.

    Developer is the only mocked component: its responsibility depends on an
    external LLM/OpenCode runtime. Reviewer, Tester, Documentation, and Git
    run against the real filesystem, pytest, and git.
    """
    repo = _setup_project(tmp_path)
    context = _make_context(str(repo))

    dev_runtime = MagicMock()
    dev_runtime.execute.return_value = "Created /health route handler."
    developer = DeveloperAgent(dev_runtime)

    dev_result = developer.execute(Task(description="Create /health route handler"), context)
    assert dev_result.success is True
    assert dev_runtime.execute.called is True

    reviewer = ReviewerAgent()
    review_report = reviewer._review(target=str(repo))
    assert "items" in review_report
    assert "summary" in review_report
    assert json.dumps(review_report)

    tester = TesterAgent()
    test_report = tester._run(target=str(repo / "tests"), dry_run=False)
    assert test_report["collected"] > 0
    assert test_report["passed"] > 0
    assert test_report["failed"] == 0
    assert json.dumps(test_report)

    doc = DocumentationAgent(docs_dir=str(repo / "docs"))
    combined_report = {
        "summary": {"passed": test_report["passed"], "failed": test_report["failed"]},
        "items": review_report["items"],
    }
    fragment = doc._generate_changelog_fragment(combined_report, dry_run=False)
    assert fragment.written is True
    assert fragment.path.exists()
    assert len(fragment.preview) > 0
    assert json.dumps(asdict(fragment), default=str)

    git = GitAgent(repository=repo)
    stage_result = git._stage()
    assert stage_result.executed is True
    assert stage_result.returncode == 0

    commit_result = git._commit("pipeline: add /health endpoint")
    assert commit_result.executed is True
    assert commit_result.returncode == 0

    push_result = git._push(approved=False)
    assert push_result.executed is False
    assert json.dumps(asdict(push_result))

    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "pipeline: add /health endpoint" in log.stdout
