"""Agent protocol and re-exports."""

from typing import Protocol, runtime_checkable

from aios.agents.contracts import (
    AgentCapabilities,
    AgentError,
    AgentExecutionEvent,
    AgentMetadata,
    AgentTask,
    RetryPolicy,
    coerce_task,
    error_from_exception,
    validate_agent_task,
)
from aios.agents.executor import AgentExecutor, make_request
from aios.agents.models import AgentResult, ExecutionOutcome, ExecutionRequest
from aios.core.task import Task

__all__ = [
    "Agent",
    "AgentResult",
    "AgentError",
    "AgentTask",
    "AgentCapabilities",
    "AgentMetadata",
    "AgentExecutionEvent",
    "RetryPolicy",
    "AgentExecutor",
    "ExecutionRequest",
    "ExecutionOutcome",
    "coerce_task",
    "error_from_exception",
    "validate_agent_task",
    "make_request",
    "Task",
]


@runtime_checkable
class Agent(Protocol):
    """Contract every agent implements."""

    name: str
    metadata: AgentMetadata
    capabilities: AgentCapabilities
    required_skills: list[str]

    def execute(self, task: Task | AgentTask, context) -> AgentResult: ...
