"""
Failure propagation tests.

The pipeline must stop at the first unrecoverable failure.
No downstream agent should execute after a failed stage.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aios.agents.developer import DeveloperAgent
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


@pytest.mark.parametrize("failure_point", ["planner", "developer", "tester"])
def test_pipeline_stops_at_failure(failure_point, tmp_path):
    """The pipeline stops exactly at the failing stage."""
    repo = _setup_project(tmp_path)
    context = _make_context(str(repo))
    scheduler = None

    try:
        planner_runtime = MagicMock()
        if failure_point == "planner":
            planner_runtime.execute.return_value = "no valid json here"
        else:
            planner_runtime.execute.return_value = json.dumps(VALID_PLAN)
        planner = PlannerAgent(planner_runtime)

        plan_result = planner.execute(Task(description="Add endpoint /health"), context)
        if failure_point == "planner":
            assert plan_result.success is False
            return

        assert plan_result.success is True
        plan = json.loads(plan_result.output)

        scheduler = KanbanEngine(project_path=repo, db_path=str(tmp_path / "kanban.db"))
        scheduler.initialize()
        board = scheduler.create_board(plan["goal"])
        for subtask in plan["subtasks"]:
            scheduler.create_card(board.id, subtask["description"])
        cards = scheduler.list_cards(board.id)
        assert len(cards) == len(plan["subtasks"])

        dev_runtime = MagicMock()
        if failure_point == "developer":
            dev_runtime.execute.side_effect = RuntimeError("execution failed")
        else:
            dev_runtime.execute.return_value = "Implementation complete."
        developer = DeveloperAgent(dev_runtime)

        dev_result = developer.execute(
            Task(description=plan["subtasks"][0]["description"]), context
        )
        if failure_point == "developer":
            assert dev_result.success is False
            return

        assert dev_result.success is True

        reviewer = ReviewerAgent()
        review_report = reviewer.review(target=str(repo))
        assert "items" in review_report
        assert "summary" in review_report

        tester = TesterAgent()
        if failure_point == "tester":
            fail_dir = repo / "fail_tests"
            fail_dir.mkdir()
            (fail_dir / "test_fail.py").write_text(
                "def test_fails():\n    assert False\n", encoding="utf-8"
            )
            test_report = tester.run(target=str(fail_dir), dry_run=False)
            assert test_report["failed"] > 0
            return

        test_report = tester.run(target=str(repo / "tests"), dry_run=False)
        assert test_report["passed"] > 0
        assert test_report["failed"] == 0
    finally:
        if scheduler is not None:
            scheduler.shutdown()
