from types import SimpleNamespace
from unittest.mock import MagicMock

from aios.agents.developer import DeveloperAgent
from aios.agents.models import AgentResult
from aios.config import ConfigEngine
from aios.context import ContextEngine
from aios.core import Kernel
from aios.core.run_result import RunResult, StageSummary
from aios.core.task import Task
from aios.events import EventsEngine
from aios.runtime import RuntimeEngine
from aios.security import SecurityEngine
from aios.workflow.models import WorkflowResult, WorkflowStage


def _make_plan_result(success: bool = True, output: str = '{"subtasks": []}') -> AgentResult:
    return AgentResult(success=success, output=output, errors=[] if success else ["boom"])


def _register_planner(kernel: Kernel) -> MagicMock:
    planner = SimpleNamespace(name="planner")
    planner.execute = MagicMock(return_value=_make_plan_result())
    kernel.register(planner)
    return planner


def _register_workflow(kernel: Kernel, result: WorkflowResult) -> MagicMock:
    workflow = SimpleNamespace(name="workflow")
    workflow.execute = MagicMock(return_value=result)
    kernel.register(workflow)
    return workflow


def _make_workflow_result(stages=(), errors=()) -> WorkflowResult:
    return WorkflowResult(
        run_id=1,
        goal="add login",
        branch=None,
        success=not errors,
        plan={"subtasks": []},
        stages=stages,
        subtask_count=0,
        completed_count=0,
        errors=errors,
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:01+00:00",
    )


def test_kernel_start_stop(tmp_path):
    kernel = Kernel(project_path=str(tmp_path))
    kernel.register(ConfigEngine(project_path=tmp_path))
    kernel.register(ContextEngine(project_path=tmp_path))
    kernel.register(RuntimeEngine())
    kernel.register(EventsEngine())
    kernel.register(SecurityEngine(project_path=tmp_path))

    kernel.start()
    status = kernel.status()

    assert status["project"] == str(tmp_path)
    assert status["engines"]["config"] == "ready"
    assert status["engines"]["context"] == "ready"
    assert status["engines"]["runtime"] in ("ready", "degraded")
    assert status["engines"]["events"] == "ready"
    assert status["engines"]["security"] == "ready"
    assert len(status["errors"]) <= 1  # runtime may be degraded without opencode

    kernel.shutdown()


def test_kernel_status_all_engines(tmp_path):
    kernel = Kernel(project_path=str(tmp_path))
    kernel.register(ConfigEngine(project_path=tmp_path))
    kernel.start()

    status = kernel.status()
    assert "config" in status["engines"]
    assert status["engines"]["config"] == "ready"


def test_kernel_get_context(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")

    kernel = Kernel(project_path=str(tmp_path))
    kernel.register(ContextEngine(project_path=tmp_path))
    kernel.start()

    context = kernel.get_context()
    assert context is not None
    assert context.project.language == "python"


def test_kernel_no_engines():
    kernel = Kernel()
    kernel.start()
    status = kernel.status()
    assert len(status["errors"]) == 0


def test_kernel_registers_agent(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")

    kernel = Kernel(project_path=str(tmp_path))
    kernel.register(ConfigEngine(project_path=tmp_path))
    kernel.register(ContextEngine(project_path=tmp_path))
    runtime = RuntimeEngine()
    kernel.register(runtime)
    kernel.register(DeveloperAgent(runtime))

    kernel.start()
    status = kernel.status()

    agent = kernel.get_engine("developer")
    assert agent is not None
    assert agent.name == "developer"
    assert status["engines"]["runtime"] in ("ready", "degraded")


class TestKernelRun:
    """Kernel.run() is the canonical entry point that resolves engines internally."""

    def test_plan_mode_routes_to_planner(self):
        kernel = Kernel()
        planner = _register_planner(kernel)
        task = Task(description="add login", task_type="plan")

        result = kernel.run(task, None, mode="plan")

        planner.execute.assert_called_once_with(task, None)
        assert isinstance(result, RunResult)
        assert result.success is True
        assert result.output == '{"subtasks": []}'

    def test_plan_run_mode_routes_to_workflow(self):
        kernel = Kernel()
        workflow = _register_workflow(kernel, _make_workflow_result())
        task = Task(description="add login", task_type="plan")

        result = kernel.run(task, None, mode="plan-run")

        workflow.execute.assert_called_once()
        assert isinstance(result, RunResult)
        assert result.success is True

    def test_default_mode_is_plan(self):
        kernel = Kernel()
        planner = _register_planner(kernel)

        result = kernel.run(Task(description="x"), None)

        planner.execute.assert_called_once()
        assert result.success is True

    def test_plan_mode_planner_failure(self):
        kernel = Kernel()
        planner = SimpleNamespace(name="planner")
        planner.execute = MagicMock(return_value=_make_plan_result(success=False))
        kernel.register(planner)

        result = kernel.run(Task(description="x"), None, mode="plan")

        assert result.success is False
        assert result.errors == ("boom",)
        assert result.stages[0].status == "failed"

    def test_plan_mode_missing_planner(self):
        result = Kernel().run(Task(description="x"), None, mode="plan")

        assert result.success is False
        assert result.errors == ("Planner agent not available.",)

    def test_plan_run_mode_missing_workflow(self):
        result = Kernel().run(Task(description="x"), None, mode="plan-run")

        assert result.success is False
        assert result.errors == ("Workflow engine not available.",)

    def test_plan_mode_planner_exception_is_friendly(self):
        kernel = Kernel()
        planner = SimpleNamespace(name="planner")
        planner.execute = MagicMock(side_effect=RuntimeError("llm timeout"))
        kernel.register(planner)

        result = kernel.run(Task(description="x"), None, mode="plan")

        assert result.success is False
        assert "llm timeout" in result.errors[0]

    def test_plan_run_mode_workflow_exception_is_friendly(self):
        kernel = Kernel()
        workflow = SimpleNamespace(name="workflow")
        workflow.execute = MagicMock(side_effect=RuntimeError("pipeline crashed"))
        kernel.register(workflow)

        result = kernel.run(Task(description="x"), None, mode="plan-run")

        assert result.success is False
        assert "pipeline crashed" in result.errors[0]

    def test_plan_run_converts_workflow_stages(self):
        stages = (
            WorkflowStage(name="planner", success=True, details={"plan": {}}),
            WorkflowStage(name="git", success=True, details={"skipped": True}),
            WorkflowStage(name="developer:1", success=False, error="exec failed"),
        )
        workflow_result = _make_workflow_result(stages=stages, errors=("exec failed",))
        kernel = Kernel()
        _register_workflow(kernel, workflow_result)

        result = kernel.run(Task(description="x"), None, mode="plan-run")

        assert result.success is False
        assert [s.status for s in result.stages] == ["success", "skipped", "failed"]
        assert result.stages[2].reason == "exec failed"

    def test_plan_run_forwards_on_stage_with_stage_summary(self):
        kernel = Kernel()
        workflow = SimpleNamespace(name="workflow")
        workflow.execute = MagicMock(return_value=_make_workflow_result())
        kernel.register(workflow)
        received: list = []

        kernel.run(
            Task(description="x"),
            None,
            mode="plan-run",
            on_stage=received.append,
        )

        workflow.execute.assert_called_once()
        callback = workflow.execute.call_args.kwargs["on_stage"]
        callback(WorkflowStage(name="planner", success=True, details={"plan": {}}))
        assert len(received) == 1
        assert isinstance(received[0], StageSummary)
        assert received[0].name == "planner"
        assert received[0].status == "success"

    def test_plan_run_skips_on_stage_when_none(self):
        kernel = Kernel()
        workflow = _register_workflow(kernel, _make_workflow_result())

        kernel.run(Task(description="x"), None, mode="plan-run", on_stage=None)

        assert workflow.execute.call_args.kwargs["on_stage"] is None
