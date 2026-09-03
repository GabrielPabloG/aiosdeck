"""Tests for BacklogRunner — sequential execution with kanban and error modes."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from aios.backlog.models import BacklogRunResult, BacklogTask
from aios.backlog.runner import BacklogRunner


@dataclass
class _MockStage:
    name: str = ""
    success: bool = True
    details: dict | None = None
    error: str | None = None
    reason: str | None = None
    status: str = "success"


@dataclass
class _MockRunResult:
    success: bool = True
    errors: tuple = ()
    stages: tuple = ()
    commit: dict | None = None
    output: str = ""


class _MockKernel:
    def __init__(self) -> None:
        self._context = None
        self.call_count = 0
        self.last_create_branch = True
        self._last_tasks: list = []

    def get_context(self):
        return self._context

    def run(  # noqa: PLR0913, PLR0917
        self,
        task,
        context,
        mode: Literal["plan", "plan-run"] = "plan",
        on_stage: Callable | None = None,
        commit_factory: Callable | None = None,
        create_branch: bool = True,
    ) -> _MockRunResult:
        self.call_count += 1
        self.last_task = task
        self._last_tasks.append(task)
        self.last_mode = mode
        self.last_commit_factory = commit_factory
        self.last_create_branch = create_branch
        return _MockRunResult(success=True, commit={"sha": f"abc{self.call_count}"})


class _MockKanbanCard:
    def __init__(self, title: str, column: str = "Todo"):
        self.title = title
        self.column = column
        self.id = 1


class _MockKanbanBoard:
    def __init__(self, name: str, id: int = 1):
        self.name = name
        self.id = id


class _MockKanbanEngine:
    def __init__(self) -> None:
        self.events: list[str] = []

    def list_boards(self):
        return [_MockKanbanBoard("backlog")]

    def list_cards(self, board_id: int):
        return [
            _MockKanbanCard("feat(backlog): add models"),
            _MockKanbanCard("fix(core): handle null"),
        ]

    def begin_work(self, card_id: int):
        self.events.append("begin_work")

    def complete_work(self, card_id: int):
        self.events.append("complete_work")

    def block_card(self, card_id: int, reason: str = ""):
        self.events.append(f"block:{reason}")


class TestBacklogRunner:
    def test_runs_all_tasks_successfully(self):
        kernel = _MockKernel()
        tasks = [
            BacklogTask(
                title="feat(backlog): add models",
                type="feat",
                scope="backlog",
                subject="add models",
            ),
            BacklogTask(
                title="fix(core): handle null", type="fix", scope="core", subject="handle null"
            ),
        ]
        runner = BacklogRunner(kernel)
        results = runner.run(tasks, stop_on_error=True)
        assert len(results) == 2
        assert all(r.status == "succeeded" for r in results)
        assert kernel.call_count == 2

    def test_stop_on_error_fail_fast(self):
        class _FailKernel(_MockKernel):
            def run(self, *args, **kwargs):
                self.call_count += 1
                if self.call_count == 1:
                    return _MockRunResult(success=True, commit={"sha": "abc1"})
                return _MockRunResult(success=False, errors=("something broke",))

        kernel = _FailKernel()
        tasks = [
            BacklogTask(title="task1", subject="task1"),
            BacklogTask(title="task2", subject="task2"),
            BacklogTask(title="task3", subject="task3"),
        ]
        runner = BacklogRunner(kernel)
        results = runner.run(tasks, stop_on_error=True)
        assert len(results) == 2
        assert results[0].status == "succeeded"
        assert results[1].status == "failed"
        assert kernel.call_count == 2

    def test_continue_on_error(self):
        class _ContinueKernel(_MockKernel):
            def run(self, *args, **kwargs):
                self.call_count += 1
                if self.call_count == 1:
                    return _MockRunResult(success=False, errors=("fail",))
                return _MockRunResult(success=True, commit={"sha": "abc2"})

        kernel = _ContinueKernel()
        tasks = [
            BacklogTask(title="t1", subject="t1"),
            BacklogTask(title="t2", subject="t2"),
        ]
        runner = BacklogRunner(kernel)
        results = runner.run(tasks, stop_on_error=False)
        assert len(results) == 2
        assert results[0].status == "failed"
        assert results[1].status == "succeeded"
        assert kernel.call_count == 2

    def test_from_index_skips_earlier_tasks(self):
        kernel = _MockKernel()
        tasks = [
            BacklogTask(title="t1", subject="t1"),
            BacklogTask(title="t2", subject="t2"),
            BacklogTask(title="t3", subject="t3"),
        ]
        runner = BacklogRunner(kernel)
        results = runner.run(tasks, from_index=2)
        assert len(results) == 3
        assert results[0].status == "skipped"
        assert results[1].status == "skipped"
        assert results[2].status == "succeeded"
        assert kernel.call_count == 1

    def test_kanban_begin_work_and_complete(self):
        kernel = _MockKernel()
        kanban = _MockKanbanEngine()
        tasks = [
            BacklogTask(
                title="feat(backlog): add models",
                type="feat",
                subject="add models",
                source="kanban:backlog",
            ),
        ]
        runner = BacklogRunner(kernel, kanban=kanban)
        runner.run(tasks)
        assert "begin_work" in kanban.events
        assert "complete_work" in kanban.events

    def test_kanban_blocked_on_failure(self):
        class _FailKernel(_MockKernel):
            def run(self, *args, **kwargs):
                return _MockRunResult(success=False, errors=("fail",))

        kernel = _FailKernel()
        kanban = _MockKanbanEngine()
        tasks = [
            BacklogTask(
                title="feat(backlog): add models",
                type="feat",
                subject="add models",
                source="kanban:backlog",
            ),
        ]
        runner = BacklogRunner(kernel, kanban=kanban)
        runner.run(tasks, stop_on_error=False)
        assert any(e.startswith("block:") for e in kanban.events)

    def test_commit_factory_derived_from_task(self):
        kernel = _MockKernel()
        tasks = [
            BacklogTask(
                title="feat(backlog): add models (v0.9.13)",
                type="feat",
                scope="backlog",
                subject="add models",
                version="v0.9.13",
            ),
        ]
        runner = BacklogRunner(kernel)
        runner.run(tasks)
        msg = kernel.last_commit_factory(None)
        assert msg == "feat(backlog): add models (v0.9.13)"

    def test_create_branch_is_false_by_default(self):
        kernel = _MockKernel()
        tasks = [BacklogTask(title="t1", subject="t1")]
        runner = BacklogRunner(kernel)
        runner.run(tasks)
        assert kernel.last_create_branch is False

    def test_create_branch_is_true_when_requested(self):
        kernel = _MockKernel()
        tasks = [BacklogTask(title="t1", subject="t1")]
        runner = BacklogRunner(kernel)
        runner.run(tasks, create_branch=True)
        assert kernel.last_create_branch is True

    def test_callbacks(self):
        kernel = _MockKernel()
        tasks = [
            BacklogTask(title="t1", subject="t1"),
            BacklogTask(title="t2", subject="t2"),
        ]
        started: list[str] = []
        ended: list[str] = []
        runner = BacklogRunner(kernel)

        def on_start(t: BacklogTask) -> None:
            started.append(t.title)

        def on_end(r: BacklogRunResult) -> None:
            ended.append(r.task.title)

        runner.run(tasks, on_task_start=on_start, on_task_end=on_end)
        assert started == ["t1", "t2"]
        assert ended == ["t1", "t2"]

    def test_empty_tasks(self):
        kernel = _MockKernel()
        runner = BacklogRunner(kernel)
        results = runner.run([])
        assert results == []
        assert kernel.call_count == 0

    def test_task_type_propagated_to_kernel(self):
        """The concrete backlog type (feat/docs/...) must reach the workflow so
        it can classify implementation vs documentation/release tasks."""
        kernel = _MockKernel()
        tasks = [
            BacklogTask(title="docs(readme): update", type="docs", subject="update"),
            BacklogTask(title="feat(core): add X", type="feat", subject="add X"),
        ]
        runner = BacklogRunner(kernel)
        runner.run(tasks)
        assert [t.task_type for t in kernel._last_tasks] == ["docs", "feat"]

    def test_execute_task_description_uses_subject(self):
        kernel = _MockKernel()
        runner = BacklogRunner(kernel)
        task = BacklogTask(title="feat(x): add models", subject="add models", type="feat")
        runner._execute_task(task)
        assert kernel.last_task.description == "add models"

    def test_execute_task_description_falls_back_to_title(self):
        """When subject is empty, the title is used as the task description."""
        kernel = _MockKernel()
        runner = BacklogRunner(kernel)
        task = BacklogTask(title="bare title", subject="", type="feat")
        runner._execute_task(task)
        assert kernel.last_task.description == "bare title"

    def test_execute_task_forwards_kernel_kwargs(self):
        kernel = _MockKernel()
        runner = BacklogRunner(kernel)
        task = BacklogTask(title="t", subject="t", type="feat")
        runner._execute_task(task, create_branch=True)
        assert kernel.last_mode == "plan-run"
        assert callable(kernel.last_commit_factory)
        assert kernel.last_create_branch is True
