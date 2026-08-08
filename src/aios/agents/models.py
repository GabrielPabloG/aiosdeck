"""Agent execution models — request, outcome, result.

``ExecutionRequest`` binds an agent (the contract Protocol) to an
``AgentTask`` for a single executor run. ``ExecutionOutcome`` carries the
terminal lifecycle state plus the resulting ``AgentResult`` (or a
standardized ``AgentError``). ``AgentResult`` is the canonical output that
every ``agent.execute(task, context)`` returns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from aios.agents.contracts import (
    STATE_CREATED,
    STATE_SUCCEEDED,
    AgentError,
    AgentTask,
    RetryPolicy,
)

if TYPE_CHECKING:
    from aios.usage.models import UsageRecord


@dataclass
class ExecutionRequest:
    """Everything the AgentExecutor needs to run one agent operation."""

    agent: Any
    task: AgentTask
    context: Any = None
    timeout: float | None = None
    retry_policy: RetryPolicy | None = None
    correlation_id: str = ""
    on_progress: Any | None = None


@dataclass(kw_only=True)
class ExecutionOutcome:
    """Neutral result of an executor run — never raw execution details."""

    status: str = STATE_CREATED
    result: Any | None = None
    error: AgentError | None = None
    duration_ms: float = 0.0
    attempts: int = 1
    retried: bool = False

    @property
    def success(self) -> bool:
        return self.status == STATE_SUCCEEDED and self.result is not None and self.result.success


@dataclass
class AgentResult:
    """Canonical agent output — every execute() returns one."""

    success: bool = True
    output: str = ""
    errors: list[str] = field(default_factory=list)
    error: AgentError | None = None
    duration_ms: float = 0.0
    status: str = STATE_SUCCEEDED
    error_code: str | None = None
    agent: str = ""
    task_id: str = ""
    correlation_id: str = ""
    usage: UsageRecord | None = None
