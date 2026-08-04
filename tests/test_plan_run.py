"""Tests for aios plan --run — execute subtasks with Fail-Fast."""

import contextlib
import io
import json
import sys
from unittest.mock import MagicMock

import pytest

from aios.agents.models import AgentResult
from aios.cli.commands import _cmd_plan
from aios.context.packet import ContextPacket, GitInfo, ProjectInfo, ToolsInfo


def _make_plan_result(subtasks: list[dict]) -> AgentResult:
    plan = {
        "goal": "test goal",
        "subtasks": subtasks,
        "risks": [],
        "unknowns": [],
    }
    return AgentResult(
        success=True,
        output=json.dumps(plan),
        errors=[],
    )


def _make_context() -> ContextPacket:
    ctx = ContextPacket()
    ctx.project = ProjectInfo(language="python", root="/tmp/test", name="test")
    ctx.tools = ToolsInfo(linter="ruff", formatter="ruff", test_runner="pytest")
    ctx.git = GitInfo(branch="main", status="clean")
    ctx.skills = ["project-dna", "coding-style"]
    return ctx


def _make_exec_success(description: str) -> AgentResult:
    return AgentResult(
        success=True,
        output=f"Executed: {description}",
        errors=[],
    )


def _make_exec_failure(description: str) -> AgentResult:
    return AgentResult(
        success=False,
        output="",
        errors=[f"Failed: {description}"],
    )


def _make_raw_args(run: bool, intent: str) -> list[str]:
    return ["--run", intent] if run else [intent]


def _make_kernel(planner: MagicMock, developer: MagicMock) -> MagicMock:
    engine_map = {"planner": planner, "developer": developer}
    kernel = MagicMock()
    kernel.get_engine.side_effect = engine_map.get
    kernel.get_context.return_value = _make_context()
    return kernel


class TestPlanRunUnit:
    """Unit tests that mock the kernel/planner/developer to verify --run behavior."""

    def test_run_flag_passes_subtasks_to_developer(self):
        """Each subtask description is passed to developer agent."""
        planner = MagicMock()
        developer = MagicMock()

        subtasks = [
            {"id": "1", "description": "Add login", "type": "code", "priority": "high",
             "dependencies": [], "estimated_complexity": "medium"},
            {"id": "2", "description": "Add tests", "type": "test", "priority": "high",
             "dependencies": ["1"], "estimated_complexity": "low"},
        ]
        planner.execute.return_value = _make_plan_result(subtasks)
        developer.execute.side_effect = [
            _make_exec_success("Add login"),
            _make_exec_success("Add tests"),
        ]

        kernel = _make_kernel(planner, developer)

        stdout = io.StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "stdout", stdout)
            _cmd_plan(
                _make_raw_args(run=True, intent="add login"),
                MagicMock(),
                lambda _: kernel,
            )

        expected_calls = len(subtasks)
        assert developer.execute.call_count == expected_calls
        assert "Add login" in developer.execute.call_args_list[0][0][0].description
        assert "Add tests" in developer.execute.call_args_list[1][0][0].description

    def test_run_flag_shows_success_status(self):
        """Visual [✓] is printed for successful subtasks."""
        planner = MagicMock()
        developer = MagicMock()

        subtasks = [
            {"id": "1", "description": "Task A", "type": "code", "priority": "high",
             "dependencies": [], "estimated_complexity": "low"},
        ]
        planner.execute.return_value = _make_plan_result(subtasks)
        developer.execute.return_value = _make_exec_success("Task A")

        kernel = _make_kernel(planner, developer)

        stdout = io.StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "stdout", stdout)
            _cmd_plan(
                _make_raw_args(run=True, intent="do task"),
                MagicMock(),
                lambda _: kernel,
            )

        output = stdout.getvalue()
        assert "✓" in output

    def test_run_flag_shows_failure_status(self):
        """Visual [✗] is printed for failed subtasks."""
        planner = MagicMock()
        developer = MagicMock()

        subtasks = [
            {"id": "1", "description": "Failing task", "type": "code", "priority": "high",
             "dependencies": [], "estimated_complexity": "low"},
        ]
        planner.execute.return_value = _make_plan_result(subtasks)
        developer.execute.return_value = _make_exec_failure("Failing task")

        kernel = _make_kernel(planner, developer)

        stdout = io.StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "stdout", stdout)
            _cmd_plan(
                _make_raw_args(run=True, intent="do task"),
                MagicMock(),
                lambda _: kernel,
            )

        output = stdout.getvalue()
        assert "✗" in output

    def test_run_flag_fail_fast_stops_on_first_error(self):
        """When a subtask fails, remaining subtasks are NOT executed."""
        planner = MagicMock()
        developer = MagicMock()

        subtasks = [
            {"id": "1", "description": "First (fails)", "type": "code", "priority": "high",
             "dependencies": [], "estimated_complexity": "low"},
            {"id": "2", "description": "Second (never runs)", "type": "test", "priority": "high",
             "dependencies": ["1"], "estimated_complexity": "low"},
        ]
        planner.execute.return_value = _make_plan_result(subtasks)
        developer.execute.return_value = _make_exec_failure("First (fails)")

        kernel = _make_kernel(planner, developer)

        _cmd_plan(
            _make_raw_args(run=True, intent="do task"),
            MagicMock(),
            lambda _: kernel,
        )

        assert developer.execute.call_count == 1

    def test_run_flag_prints_summary_count(self):
        """After execution, prints how many tasks ran (X/Y completed)."""
        planner = MagicMock()
        developer = MagicMock()

        subtasks = [
            {"id": "1", "description": "Task 1", "type": "code", "priority": "high",
             "dependencies": [], "estimated_complexity": "low"},
            {"id": "2", "description": "Task 2", "type": "code", "priority": "medium",
             "dependencies": ["1"], "estimated_complexity": "low"},
        ]
        planner.execute.return_value = _make_plan_result(subtasks)
        developer.execute.side_effect = [
            _make_exec_success("Task 1"),
            _make_exec_success("Task 2"),
        ]

        kernel = _make_kernel(planner, developer)

        stdout = io.StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "stdout", stdout)
            _cmd_plan(
                _make_raw_args(run=True, intent="do task"),
                MagicMock(),
                lambda _: kernel,
            )

        output = stdout.getvalue()
        assert "2/2" in output

    def test_run_flag_handles_planner_failure(self):
        """If planner fails, print error and exit — no developer calls."""
        planner = MagicMock()
        developer = MagicMock()

        planner.execute.return_value = AgentResult(
            success=False, output="", errors=["Planner error"]
        )

        kernel = _make_kernel(planner, developer)

        stderr = io.StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "stderr", stderr)
            with contextlib.suppress(SystemExit):
                _cmd_plan(
                    _make_raw_args(run=True, intent="bad plan"),
                    MagicMock(),
                    lambda _: kernel,
                )

        developer.execute.assert_not_called()
        assert "Planner error" in stderr.getvalue()

    def test_run_flag_strips_run_from_intent(self):
        """--run flag is not included in the intent string passed to planner."""
        planner = MagicMock()
        developer = MagicMock()

        subtasks = [
            {"id": "1", "description": "Do something", "type": "code", "priority": "high",
             "dependencies": [], "estimated_complexity": "low"},
        ]
        planner.execute.return_value = _make_plan_result(subtasks)
        developer.execute.return_value = _make_exec_success("Do something")

        kernel = _make_kernel(planner, developer)

        _cmd_plan(
            _make_raw_args(run=True, intent="add tests"),
            MagicMock(),
            lambda _: kernel,
        )

        task_arg = planner.execute.call_args[0][0]
        assert task_arg.description == "add tests"
        assert "--run" not in task_arg.description
