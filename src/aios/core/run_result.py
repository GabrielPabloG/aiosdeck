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
    tool_calls: int = 0
    tool_names: tuple[str, ...] = ()
    tool_durations_ms: tuple[float, ...] = ()
    llm_turns: int = 0
    total_cost: float = 0.0
    tokens: dict[str, Any] = field(default_factory=dict)
    model: str = ""
    provider: str = ""
    fallback_used: bool = False
    steps_used: int = 0
    repeated_tool_calls: int = 0
    turn_sequence: tuple[str, ...] = ()
    exit_reason: str = "stop"

    @classmethod
    def from_agent(cls, agent_result) -> RunResult:
        """Wrap a single agent outcome (used for planner-only runs)."""
        failed = not agent_result.success
        return cls(
            success=agent_result.success,
            output=getattr(agent_result, "output", None),
            errors=tuple(agent_result.errors),
            tool_calls=getattr(agent_result, "tool_calls", 0),
            tool_names=tuple(getattr(agent_result, "tool_names", [])),
            tool_durations_ms=tuple(getattr(agent_result, "tool_durations_ms", [])),
            llm_turns=getattr(agent_result, "llm_turns", 0),
            total_cost=getattr(agent_result, "total_cost", 0.0),
            tokens=getattr(agent_result, "tokens", {}),
            model=getattr(agent_result, "model", ""),
            provider=getattr(agent_result, "provider", ""),
            fallback_used=getattr(agent_result, "fallback_used", False),
            steps_used=getattr(agent_result, "steps_used", 0),
            repeated_tool_calls=getattr(agent_result, "repeated_tool_calls", 0),
            turn_sequence=tuple(getattr(agent_result, "turn_sequence", [])),
            exit_reason=getattr(agent_result, "exit_reason", "stop"),
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
