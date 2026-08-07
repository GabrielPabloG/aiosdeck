"""Tests for aios plan --run — execute subtasks with Fail-Fast."""

import contextlib
import io
import json
import sys
from unittest.mock import MagicMock

import pytest

from aios.agents.models import AgentResult
from aios.agents.reviewer import ReviewerAgent
from aios.cli.commands import _cmd_plan
from aios.cli.main import _create_kernel
from aios.context.packet import ContextPacket, GitInfo, ProjectInfo, ToolsInfo
from aios.events import EventsEngine
from aios.scheduler import KanbanEngine
from aios.workflow import WorkflowEngine
from aios.workflow.models import WorkflowResult, WorkflowStage


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


def _make_kernel_with_scheduler(
    planner: MagicMock,
    developer: MagicMock,
    scheduler: KanbanEngine,
    events: EventsEngine,
    workflow=None,
) -> MagicMock:
    engine_map = {
        "planner": planner,
        "developer": developer,
        "scheduler": scheduler,
        "events": events,
    }
    if workflow is not None:
        engine_map["workflow"] = workflow
    kernel = MagicMock()
    kernel.get_engine.side_effect = engine_map.get
    kernel.get_context.return_value = _make_context()
    return kernel


def _make_kernel_with_workflow(
    planner: MagicMock, developer: MagicMock, workflow: MagicMock
) -> MagicMock:
    engine_map = {"planner": planner, "developer": developer, "workflow": workflow}
    kernel = MagicMock()
    kernel.get_engine.side_effect = engine_map.get
    kernel.get_context.return_value = _make_context()
    return kernel


def _make_workflow_result(
    success: bool = True,
    subtasks: list[dict] | None = None,
    completed: int | None = None,
    errors: tuple[str, ...] = (),
):
    plan = {
        "goal": "add login",
        "subtasks": subtasks or [{"description": "Task A"}, {"description": "Task B"}],
    }
    n = len(plan["subtasks"])
    return WorkflowResult(
        run_id=1,
        goal="add login",
        branch=None,
        success=success,
        plan=plan,
        stages=(
            WorkflowStage(name="planner", success=True, details={"plan": plan}),
            *(WorkflowStage(name=f"developer:{i + 1}", success=True) for i in range(n)),
        ),
        subtask_count=n,
        completed_count=n if completed is None else completed,
        errors=errors,
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:01+00:00",
    )


class TestPlanRunWorkflow:
    """plan --run delegates to the WorkflowEngine."""

    def test_run_invokes_workflow_execute(self):
        """The workflow engine receives the task, context, and an on_stage hook."""
        planner = MagicMock()
        developer = MagicMock()
        workflow = MagicMock()
        workflow.execute.return_value = _make_workflow_result()
        kernel = _make_kernel_with_workflow(planner, developer, workflow)

        _cmd_plan(_make_raw_args(run=True, intent="add login"), MagicMock(), lambda _: kernel)

        assert workflow.execute.call_count == 1
        task_arg = workflow.execute.call_args[0][0]
        assert task_arg.description == "add login"
        assert workflow.execute.call_args.kwargs["on_stage"] is not None

    def test_run_renders_workflow_summary(self):
        """Per-task marks and the X/Y summary render from the workflow result."""
        planner = MagicMock()
        developer = MagicMock()
        workflow = MagicMock()
        workflow.execute.return_value = _make_workflow_result()
        kernel = _make_kernel_with_workflow(planner, developer, workflow)

        stdout = io.StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "stdout", stdout)
            _cmd_plan(_make_raw_args(run=True, intent="add login"), MagicMock(), lambda _: kernel)

        assert "2/2 tasks completed" in stdout.getvalue()

    def test_run_callback_renders_plan_list(self):
        """The plan list is rendered when the planner stage fires."""
        planner = MagicMock()
        developer = MagicMock()
        workflow = MagicMock()
        workflow.execute.return_value = _make_workflow_result()
        kernel = _make_kernel_with_workflow(planner, developer, workflow)

        stderr = io.StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "stderr", stderr)
            _cmd_plan(_make_raw_args(run=True, intent="add login"), MagicMock(), lambda _: kernel)
            on_stage = workflow.execute.call_args.kwargs["on_stage"]
            on_stage(
                WorkflowStage(
                    name="planner",
                    success=True,
                    details={
                        "plan": {"subtasks": [{"description": "Task A"}, {"description": "Task B"}]}
                    },
                )
            )

        output = stderr.getvalue()
        assert "Plano de Execução (2 tarefas):" in output
        assert "• Task A" in output

    def test_run_workflow_flag_disabled_uses_direct_path(self, monkeypatch):
        """AIOS_USE_WORKFLOW_ENGINE=0 falls back to the direct path."""
        monkeypatch.setenv("AIOS_USE_WORKFLOW_ENGINE", "0")
        planner = MagicMock()
        developer = MagicMock()
        workflow = MagicMock()
        planner.execute.return_value = _make_plan_result(
            [
                {
                    "id": "1",
                    "description": "Task A",
                    "type": "code",
                    "priority": "high",
                    "dependencies": [],
                    "estimated_complexity": "low",
                }
            ]
        )
        developer.execute.return_value = _make_exec_success("Task A")
        kernel = _make_kernel_with_workflow(planner, developer, workflow)

        _cmd_plan(_make_raw_args(run=True, intent="add login"), MagicMock(), lambda _: kernel)

        workflow.execute.assert_not_called()
        assert developer.execute.call_count == 1

    def test_run_without_workflow_uses_direct_path(self):
        """When no workflow engine is registered, the direct path still works."""
        planner = MagicMock()
        developer = MagicMock()
        planner.execute.return_value = _make_plan_result(
            [
                {
                    "id": "1",
                    "description": "Task A",
                    "type": "code",
                    "priority": "high",
                    "dependencies": [],
                    "estimated_complexity": "low",
                }
            ]
        )
        developer.execute.return_value = _make_exec_success("Task A")
        kernel = _make_kernel(planner, developer)

        _cmd_plan(_make_raw_args(run=True, intent="add login"), MagicMock(), lambda _: kernel)

        assert developer.execute.call_count == 1

    def test_create_kernel_registers_workflow(self, tmp_path):
        """The production kernel factory registers the workflow engine."""
        kernel = _create_kernel(tmp_path)

        workflow = kernel.get_engine("workflow")
        assert workflow is not None
        assert workflow.name == "workflow"


class TestPlanRunUnit:
    """Unit tests that mock the kernel/planner/developer to verify --run behavior."""

    def test_run_flag_passes_subtasks_to_developer(self):
        """Each subtask description is passed to developer agent."""
        planner = MagicMock()
        developer = MagicMock()

        subtasks = [
            {
                "id": "1",
                "description": "Add login",
                "type": "code",
                "priority": "high",
                "dependencies": [],
                "estimated_complexity": "medium",
            },
            {
                "id": "2",
                "description": "Add tests",
                "type": "test",
                "priority": "high",
                "dependencies": ["1"],
                "estimated_complexity": "low",
            },
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
            {
                "id": "1",
                "description": "Task A",
                "type": "code",
                "priority": "high",
                "dependencies": [],
                "estimated_complexity": "low",
            },
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
            {
                "id": "1",
                "description": "Failing task",
                "type": "code",
                "priority": "high",
                "dependencies": [],
                "estimated_complexity": "low",
            },
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
            {
                "id": "1",
                "description": "First (fails)",
                "type": "code",
                "priority": "high",
                "dependencies": [],
                "estimated_complexity": "low",
            },
            {
                "id": "2",
                "description": "Second (never runs)",
                "type": "test",
                "priority": "high",
                "dependencies": ["1"],
                "estimated_complexity": "low",
            },
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
            {
                "id": "1",
                "description": "Task 1",
                "type": "code",
                "priority": "high",
                "dependencies": [],
                "estimated_complexity": "low",
            },
            {
                "id": "2",
                "description": "Task 2",
                "type": "code",
                "priority": "medium",
                "dependencies": ["1"],
                "estimated_complexity": "low",
            },
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
            {
                "id": "1",
                "description": "Do something",
                "type": "code",
                "priority": "high",
                "dependencies": [],
                "estimated_complexity": "low",
            },
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

    def test_run_prints_plan_and_initial_backlog_before_execution(self, tmp_path):
        """Plan list and initial board (all cards in Backlog) print before execution."""
        planner = MagicMock()
        developer = MagicMock()

        subtasks = [
            {
                "id": str(i),
                "description": f"Task {i}",
                "type": "code",
                "priority": "high",
                "dependencies": [],
                "estimated_complexity": "low",
            }
            for i in range(3)
        ]
        planner.execute.return_value = _make_plan_result(subtasks)
        developer.execute.return_value = _make_exec_success("ok")

        events = EventsEngine()
        events.initialize()
        scheduler = KanbanEngine(project_path=tmp_path, db_path=str(tmp_path / "kanban.db"))
        scheduler.initialize()
        kernel = _make_kernel_with_scheduler(planner, developer, scheduler, events)

        stderr = io.StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "stderr", stderr)
            _cmd_plan(
                _make_raw_args(run=True, intent="do all"),
                MagicMock(),
                lambda _: kernel,
            )

        output = stderr.getvalue()
        assert "Plano de Execução (3 tarefas):" in output
        assert "• Task 0" in output
        assert "• Task 1" in output
        assert developer.execute.call_count == len(subtasks)
        scheduler.shutdown()

    def test_run_blocks_card_when_subtask_fails(self, tmp_path):
        """A failing subtask leaves its card blocked in the workflow kanban."""
        planner = MagicMock()
        developer = MagicMock()

        subtasks = [
            {
                "id": "1",
                "description": "First (ok)",
                "type": "code",
                "priority": "high",
                "dependencies": [],
                "estimated_complexity": "low",
            },
            {
                "id": "2",
                "description": "Second (fails)",
                "type": "code",
                "priority": "high",
                "dependencies": ["1"],
                "estimated_complexity": "low",
            },
        ]
        planner.execute.return_value = _make_plan_result(subtasks)
        developer.execute.side_effect = [
            _make_exec_success("First (ok)"),
            _make_exec_failure("Second (fails)"),
        ]

        events = EventsEngine()
        events.initialize()
        scheduler = KanbanEngine(project_path=tmp_path, db_path=str(tmp_path / "kanban.db"))
        scheduler.initialize()
        workflow = WorkflowEngine(
            planner=planner,
            scheduler=scheduler,
            developer=developer,
            reviewer=ReviewerAgent(),
            tester=None,
            documentation=None,
            git=None,
            project_path=tmp_path,
        )
        kernel = _make_kernel_with_scheduler(planner, developer, scheduler, events, workflow)

        stderr = io.StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "stderr", stderr)
            with contextlib.suppress(SystemExit):
                _cmd_plan(
                    _make_raw_args(run=True, intent="do it"),
                    MagicMock(),
                    lambda _: kernel,
                )

        board = scheduler.list_boards()[0]
        cards = scheduler.list_cards(board.id)
        assert cards[0].column == "Done"
        assert cards[0].blocked is False
        assert cards[1].column == "InProgress"
        assert cards[1].blocked is True
        assert cards[1].block_reason == "execution failed"
        scheduler.shutdown()
