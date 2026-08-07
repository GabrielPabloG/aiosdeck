"""Workflow models — execution state, results, and health."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from aios.agents.documentation import ChangelogFragment
from aios.agents.git import GitOperation
from aios.core.task import Task
from aios.scheduler import KanbanBoard, KanbanCard


class RunIdGenerator(Protocol):
    """Generates the next run identifier."""

    def next(self) -> int: ...


class InMemoryRunIdGenerator:
    """In-memory run counter. Replaceable by a persistent repository later."""

    def __init__(self) -> None:
        self._counter = 0

    def next(self) -> int:
        self._counter += 1
        return self._counter


class WorkflowConfigurationError(Exception):
    """Raised when a required workflow dependency is missing."""


@dataclass
class WorkflowStage:
    """Outcome of a single pipeline stage."""

    name: str
    success: bool
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class _WorkflowContext:
    """Internal execution state. Not part of the public API."""

    task: Task
    run_id: int
    goal: str
    started_at: str
    plan: dict | None = None
    branch: str | None = None
    board: KanbanBoard | None = None
    cards: list[KanbanCard] = field(default_factory=list)
    review_report: dict | None = None
    test_report: dict | None = None
    fragment: ChangelogFragment | None = None
    commit: GitOperation | None = None
    stages: list[WorkflowStage] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    completed_count: int = 0
    subtask_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    finished_at: str | None = None


@dataclass(frozen=True)
class WorkflowResult:
    """Immutable final result of a workflow run."""

    run_id: int
    goal: str
    branch: str | None
    success: bool
    plan: dict | None
    stages: tuple[WorkflowStage, ...]
    subtask_count: int
    completed_count: int
    errors: tuple[str, ...]
    started_at: str
    finished_at: str | None

    @classmethod
    def from_context(cls, ctx: _WorkflowContext) -> WorkflowResult:
        return cls(
            run_id=ctx.run_id,
            goal=ctx.goal,
            branch=ctx.branch,
            success=not ctx.errors,
            plan=ctx.plan,
            stages=tuple(ctx.stages),
            subtask_count=ctx.subtask_count,
            completed_count=ctx.completed_count,
            errors=tuple(ctx.errors),
            started_at=ctx.started_at,
            finished_at=ctx.finished_at,
        )


@dataclass
class WorkflowHealth:
    """Health status per pipeline agent.

    ``optional`` names (e.g. tester, documentation, git) are not required for
    the pipeline to be healthy: a missing optional agent just skips its stage.
    """

    agents: dict[str, bool]
    optional: list[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        required = [name for name in self.agents if name not in self.optional]
        return all(self.agents[name] for name in required)

    @property
    def missing_agents(self) -> list[str]:
        required = [name for name in self.agents if name not in self.optional]
        return [name for name in required if not self.agents[name]]
