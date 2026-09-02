"""BacklogRunner — executes backlog tasks sequentially through Kernel.run."""

import time
from collections.abc import Callable
from typing import Any

from aios.backlog.models import BacklogRunResult, BacklogTask
from aios.core.task import Task


class BacklogRunner:
    def __init__(self, kernel, kanban=None, telemetry=None) -> None:
        self._kernel = kernel
        self._kanban = kanban
        self._telemetry = telemetry

    def run(  # noqa: PLR0912, PLR0913, PLR0915, PLR0917 - sequential execution with multiple modes
        self,
        tasks: list[BacklogTask],
        stop_on_error: bool = True,
        from_index: int = 0,
        on_task_start: Callable[[BacklogTask], None] | None = None,
        on_task_end: Callable[[BacklogRunResult], None] | None = None,
        create_branch: bool = False,
    ) -> list[BacklogRunResult]:
        results: list[BacklogRunResult] = []
        for i, task in enumerate(tasks):
            if i < from_index:
                results.append(BacklogRunResult(task=task, status="skipped", duration_ms=0.0))
                continue

            if on_task_start:
                on_task_start(task)

            self._update_kanban(task, "InProgress")
            started = time.monotonic()
            error = ""
            status = "succeeded"
            commit_sha = ""

            try:
                result = self._execute_task(task, create_branch=create_branch)
                if not result.success:
                    error = "; ".join(result.errors) if result.errors else "task failed"
                    status = "failed"
                commit_sha = self._extract_commit_sha(result)
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
                status = "failed"

            duration_ms = (time.monotonic() - started) * 1000
            run_result = BacklogRunResult(
                task=task,
                status=status,
                commit_sha=commit_sha,
                duration_ms=duration_ms,
                error=error,
            )
            results.append(run_result)

            if status == "succeeded":
                self._update_kanban(task, "Done")
            else:
                self._update_kanban(task, "blocked", reason=error)

            if on_task_end:
                on_task_end(run_result)

            if status == "failed" and stop_on_error:
                break

        return results

    def _execute_task(self, task: BacklogTask, create_branch: bool = False) -> Any:
        commit_factory = self._build_commit_factory(task)
        description = task.subject or task.title
        t = Task(description=description, task_type=task.type)
        context = self._kernel.get_context()
        return self._kernel.run(
            t,
            context,
            mode="plan-run",
            commit_factory=commit_factory,
            create_branch=create_branch,
        )

    def _build_commit_factory(self, task: BacklogTask) -> Callable[[Any], str]:
        def factory(_ctx) -> str:
            scope_part = f"({task.scope})" if task.scope else ""
            version_part = f" ({task.version})" if task.version else ""
            return f"{task.type}{scope_part}: {task.subject}{version_part}"

        return factory

    @staticmethod
    def _extract_commit_sha(result: Any) -> str:
        commit = getattr(result, "commit", None)
        if commit and isinstance(commit, dict):
            return commit.get("sha", "")
        if hasattr(result, "stages"):
            for stage in result.stages:
                details = getattr(stage, "details", {}) or {}
                commit_info = details.get("commit") or {}
                if isinstance(commit_info, dict):
                    return commit_info.get("sha", "")
        return ""

    def _update_kanban(self, task: BacklogTask, column: str, reason: str = "") -> None:
        if self._kanban is None:
            return
        boards = self._kanban.list_boards()
        board = None
        for b in boards:
            if task.source and task.source.startswith("kanban:"):
                board_name = task.source.split(":", 1)[1]
                if b.name == board_name:
                    board = b
                    break
        if board is None:
            return
        cards = self._kanban.list_cards(board.id)
        for card in cards:
            if card.title == task.title:
                if column == "blocked":
                    self._kanban.block_card(card.id, reason=reason)
                elif column == "InProgress":
                    self._kanban.begin_work(card.id)
                elif column == "Done":
                    self._kanban.complete_work(card.id)
                break
