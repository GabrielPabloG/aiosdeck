"""RunResult — standardized execution outcome returned by Kernel.run().

The CLI consumes only this shape. It never needs to know whether a single
planner agent, the full workflow pipeline, or a future engine produced the
result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

StageStatus = Literal["success", "failed", "skipped"]


@dataclass(frozen=True)
class StageSummary:
    """Normalized outcome of a single pipeline stage."""

    name: str
    status: StageStatus = "success"
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunResult:
    """Immutable final result of a Kernel.run() invocation."""

    success: bool
    stages: tuple[StageSummary, ...] = ()
    errors: tuple[str, ...] = ()
    output: str | None = None
    plan: dict[str, Any] | None = None
    subtask_count: int = 0
    completed_count: int = 0
    started_at: str | None = None
    finished_at: str | None = None

    @classmethod
    def from_agent(cls, agent_result) -> RunResult:
        """Wrap a single agent outcome (used for planner-only runs)."""
        failed = not agent_result.success
        return cls(
            success=agent_result.success,
            output=getattr(agent_result, "output", None),
            errors=tuple(agent_result.errors),
            stages=(
                StageSummary(
                    name="planner",
                    status="failed" if failed else "success",
                    reason=agent_result.errors[0] if failed and agent_result.errors else None,
                ),
            ),
        )

    @classmethod
    def from_workflow(cls, workflow_result) -> RunResult:
        """Wrap a WorkflowEngine outcome into the standard contract."""
        return cls(
            success=workflow_result.success,
            stages=tuple(stage_to_summary(s) for s in workflow_result.stages),
            errors=tuple(workflow_result.errors),
            plan=workflow_result.plan,
            subtask_count=workflow_result.subtask_count,
            completed_count=workflow_result.completed_count,
            started_at=workflow_result.started_at,
            finished_at=workflow_result.finished_at,
        )


def stage_to_summary(stage) -> StageSummary:
    """Normalize an engine stage object (duck-typed) into a StageSummary."""
    details = getattr(stage, "details", None) or {}
    if details.get("skipped"):
        return StageSummary(name=stage.name, status="skipped", details=details)
    if stage.success:
        return StageSummary(name=stage.name, status="success", details=details)
    return StageSummary(
        name=stage.name,
        status="failed",
        reason=getattr(stage, "error", None),
        details=details,
    )
