"""Tests for `aios plan` — the CLI is thin and delegates to Kernel.run().

The CLI only parses arguments and renders results. It never reaches into
individual agents (planner/developer/workflow) directly.
"""

import contextlib
import io
import json
import sys
from unittest.mock import MagicMock

import pytest

from aios.agents import AgentExecutor
from aios.agents.developer import DeveloperAgent
from aios.agents.models import AgentResult
from aios.agents.planner import PlannerAgent
from aios.agents.reviewer import ReviewerAgent
from aios.cli.commands.exec_cmds import cmd_plan as _cmd_plan
from aios.core.factory import create_kernel
from aios.context import ContextEngine
from aios.context.packet import ContextPacket, GitInfo, ProjectInfo, ToolsInfo
from aios.core import Kernel, RunResult, StageSummary
from aios.scheduler import KanbanEngine
from aios.workflow import WorkflowEngine


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


def _make_run_result(
    success: bool = True,
    subtasks: list[dict] | None = None,
    completed: int | None = None,
    errors: tuple[str, ...] = (),
    output: str | None = None,
) -> RunResult:
    if subtasks is None:
        subtasks = [{"description": "Task A"}, {"description": "Task B"}]
    plan = {"goal": "add login", "subtasks": subtasks}
    n = len(plan["subtasks"])
    return RunResult(
        success=success,
        output=output,
        plan=plan,
        subtask_count=n,
        completed_count=n if completed is None else completed,
        errors=errors,
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:01+00:00",
    )


def _make_kernel(result: RunResult | None = None) -> MagicMock:
    kernel = MagicMock()
    kernel.run.return_value = result or _make_run_result()
    kernel.get_context.return_value = _make_context()
    return kernel


class TestPlanDelegatesToKernel:
    """The CLI calls kernel.run() and performs zero orchestration itself."""

    def test_plan_calls_kernel_run_exactly_once(self):
        kernel = _make_kernel()

        _cmd_plan(["add login"], MagicMock(), lambda _: kernel)

        assert kernel.run.call_count == 1

    def test_plan_run_passes_task_context_and_mode(self):
        kernel = _make_kernel()

        _cmd_plan(["--run", "add login"], MagicMock(), lambda _: kernel)

        task_arg = kernel.run.call_args[0][0]
        assert task_arg.description == "add login"
        assert kernel.run.call_args[0][1] is not None
        assert kernel.run.call_args.kwargs["mode"] == "plan-run"
        assert kernel.run.call_args.kwargs["on_stage"] is not None

    def test_plan_only_mode_passes_mode_plan_and_no_callback(self):
        kernel = _make_kernel(_make_run_result(output="{}", subtasks=[]))

        _cmd_plan(["add login"], MagicMock(), lambda _: kernel)

        assert kernel.run.call_args.kwargs["mode"] == "plan"
        assert kernel.run.call_args.kwargs["on_stage"] is None

    def test_plan_does_not_lookup_engines(self):
        kernel = _make_kernel()

        _cmd_plan(["--run", "add login"], MagicMock(), lambda _: kernel)

        kernel.get_engine.assert_not_called()

    def test_plan_does_not_start_subprocess_loop(self):
        """No developer loop: the workflow owns execution."""
        kernel = _make_kernel()

        _cmd_plan(["--run", "add login"], MagicMock(), lambda _: kernel)

        assert kernel.run.call_args.kwargs["mode"] == "plan-run"

    def test_create_kernel_registers_workflow(self, tmp_path):
        """The production kernel factory registers the workflow engine."""
        kernel = create_kernel(tmp_path)

        workflow = kernel.get_engine("workflow")
        assert workflow is not None
        assert workflow.name == "workflow"


class TestPlanRendering:
    """The CLI renders the standardized RunResult / StageSummary only."""

    def test_plan_run_renders_summary(self):
        kernel = _make_kernel(_make_run_result())

        stdout = io.StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "stdout", stdout)
            _cmd_plan(["--run", "add login"], MagicMock(), lambda _: kernel)

        assert "2/2 tasks completed" in stdout.getvalue()

    def test_plan_run_renders_partial_summary(self):
        kernel = _make_kernel(_make_run_result(completed=1))

        stdout = io.StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "stdout", stdout)
            _cmd_plan(["--run", "add login"], MagicMock(), lambda _: kernel)

        assert "1/2 tasks completed" in stdout.getvalue()

    def test_plan_only_renders_output(self):
        kernel = _make_kernel(_make_run_result(output='{"goal": "x", "subtasks": []}', subtasks=[]))

        stdout = io.StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "stdout", stdout)
            _cmd_plan(["add login"], MagicMock(), lambda _: kernel)

        assert '{"goal": "x", "subtasks": []}' in stdout.getvalue()

    def test_on_stage_callback_renders_plan_list(self):
        kernel = _make_kernel(_make_run_result())

        stderr = io.StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "stderr", stderr)
            _cmd_plan(["--run", "add login"], MagicMock(), lambda _: kernel)
            on_stage = kernel.run.call_args.kwargs["on_stage"]
            on_stage(
                StageSummary(
                    name="planner",
                    status="success",
                    details={
                        "plan": {"subtasks": [{"description": "Task A"}, {"description": "Task B"}]}
                    },
                )
            )

        output = stderr.getvalue()
        assert "Plano de Execução (2 tarefas):" in output
        assert "• Task A" in output

    def test_on_stage_callback_renders_developer_marks(self):
        kernel = _make_kernel(_make_run_result())

        stdout = io.StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "stdout", stdout)
            _cmd_plan(["--run", "add login"], MagicMock(), lambda _: kernel)
            on_stage = kernel.run.call_args.kwargs["on_stage"]
            on_stage(
                StageSummary(
                    name="developer:1",
                    status="success",
                    details={"description": "Task A"},
                )
            )
            on_stage(
                StageSummary(
                    name="developer:2",
                    status="failed",
                    details={"description": "Task B"},
                )
            )

        output = stdout.getvalue()
        assert "[✓] Task A" in output
        assert "[✗] Task B" in output

    def test_on_stage_callback_skips_optional_stage(self):
        kernel = _make_kernel(_make_run_result())

        stdout = io.StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "stdout", stdout)
            _cmd_plan(["--run", "add login"], MagicMock(), lambda _: kernel)
            on_stage = kernel.run.call_args.kwargs["on_stage"]
            before = stdout.getvalue()
            on_stage(StageSummary(name="tester", status="skipped"))

        assert stdout.getvalue() == before


class TestPlanErrors:
    """Errors propagate through RunResult.errors with a friendly message."""

    def test_failure_prints_errors_and_exits(self):
        kernel = _make_kernel(_make_run_result(success=False, errors=("boom",)))

        stderr = io.StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "stderr", stderr)
            with pytest.raises(SystemExit):
                _cmd_plan(["--run", "add login"], MagicMock(), lambda _: kernel)

        assert "Error: boom" in stderr.getvalue()

    def test_no_intent_prints_usage(self):
        kernel = _make_kernel()

        stderr = io.StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "stderr", stderr)
            with pytest.raises(SystemExit):
                _cmd_plan([], MagicMock(), lambda _: kernel)

        assert "Usage: aios plan <intent>" in stderr.getvalue()


class TestPlanRunIntegration:
    """Real Kernel + real WorkflowEngine; only the LLM agents are stubbed."""

    def test_plan_run_without_optional_agents_completes(self, tmp_path):
        """Missing tester/documentation/git degrade gracefully — pipeline continues."""
        subtask = {
            "id": "1",
            "description": "Task A",
            "type": "code",
            "priority": "high",
            "dependencies": [],
            "estimated_complexity": "low",
        }
        planner_runtime = MagicMock()
        planner_runtime.execute.return_value = AgentResult(
            output=json.dumps(
                {"goal": "add login", "subtasks": [subtask], "risks": [], "unknowns": []}
            )
        )
        dev_runtime = MagicMock()
        dev_runtime.execute.return_value = AgentResult(output="Executed: Task A")
        executor = AgentExecutor()

        scheduler = KanbanEngine(project_path=tmp_path, db_path=str(tmp_path / "kanban.db"))
        scheduler.initialize()
        workflow = WorkflowEngine(
            planner=PlannerAgent(planner_runtime),
            scheduler=scheduler,
            developer=DeveloperAgent(dev_runtime),
            reviewer=ReviewerAgent(),
            tester=None,
            documentation=None,
            git=None,
            project_path=tmp_path,
            executor=executor,
        )
        kernel = Kernel(project_path=str(tmp_path))
        kernel.set_executor(executor)
        kernel.register(ContextEngine(project_path=tmp_path))
        kernel.register(workflow)

        stdout = io.StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "stdout", stdout)
            with contextlib.suppress(SystemExit):
                _cmd_plan(["--run", "add login"], tmp_path, lambda _: kernel)

        assert "1/1 tasks completed" in stdout.getvalue()
        assert "[✓] Task A" in stdout.getvalue()
        scheduler.shutdown()

    def test_plan_run_workflow_exception_is_friendly(self):
        """An internal workflow exception surfaces as a friendly error message."""
        workflow = MagicMock()
        workflow.execute.side_effect = RuntimeError("pipeline crashed")
        workflow.name = "workflow"
        kernel = Kernel(project_path="/tmp/test")
        kernel.register(workflow)

        stderr = io.StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "stderr", stderr)
            with pytest.raises(SystemExit):
                _cmd_plan(["--run", "add login"], MagicMock(), lambda _: kernel)


# ---------------------------------------------------------------------------
# Cycle 1 contract tests — high-density mutation targets
# ---------------------------------------------------------------------------


def test_run_result_from_agent_maps_all_fields():
    ar = AgentResult(
        success=True,
        output="ok",
        errors=["e1"],
        tool_calls=5,
        tool_names=["grep", "ls"],
        tool_durations_ms=[1.0, 2.0],
        llm_turns=3,
        total_cost=0.01,
        tokens={"in": 100},
        model="gpt-4o",
        provider="openai",
        fallback_used=True,
        steps_used=10,
        repeated_tool_calls=2,
        turn_sequence=["think", "act"],
        exit_reason="stop",
    )
    rr = RunResult.from_agent(ar)

    assert rr.success is True
    assert rr.output == "ok"
    assert rr.errors == ("e1",)
    assert rr.tool_calls == 5
    assert rr.tool_names == ("grep", "ls")
    assert rr.tool_durations_ms == (1.0, 2.0)
    assert rr.llm_turns == 3
    assert rr.total_cost == 0.01
    assert rr.tokens == {"in": 100}
    assert rr.model == "gpt-4o"
    assert rr.provider == "openai"
    assert rr.fallback_used is True
    assert rr.steps_used == 10
    assert rr.repeated_tool_calls == 2
    assert rr.turn_sequence == ("think", "act")
    assert rr.exit_reason == "stop"
    assert len(rr.stages) == 1
    assert rr.stages[0].name == "planner"
    assert rr.stages[0].status == "success"


def test_run_result_from_agent_failed_preserves_error():
    ar = AgentResult(
        success=False,
        output="",
        errors=["boom", "secondary"],
    )
    rr = RunResult.from_agent(ar)

    assert rr.success is False
    assert rr.errors == ("boom", "secondary")
    assert rr.stages[0].status == "failed"
    assert rr.stages[0].reason == "boom"


def test_run_result_from_agent_defaults():
    ar = AgentResult(success=True, output="x")
    rr = RunResult.from_agent(ar)

    assert rr.tool_calls == 0
    assert rr.tool_names == ()
    assert rr.tool_durations_ms == ()
    assert rr.llm_turns == 0
    assert rr.total_cost == 0.0
    assert rr.tokens == {}
    assert rr.model == ""
    assert rr.provider == ""
    assert rr.fallback_used is False
    assert rr.steps_used == 0
    assert rr.repeated_tool_calls == 0
    assert rr.turn_sequence == ()
    assert rr.exit_reason == "stop"


def test_create_kernel_registers_all_engines(tmp_path):
    kernel = create_kernel(tmp_path)

    expected = [
        "config",
        "context",
        "memory",
        "learning",
        "scheduler",
        "events",
        "telemetry",
        "knowledge",
        "security",
        "developer",
        "planner",
        "reviewer",
        "research",
        "runtime",
        "workflow",
    ]
    for name in expected:
        engine = kernel.get_engine(name)
        assert engine is not None, f"engine '{name}' not registered"
        assert getattr(engine, "name", None) == name
