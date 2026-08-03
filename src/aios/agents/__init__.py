"""Agent protocol and re-exports."""

from typing import Protocol, runtime_checkable

from aios.agents.executor import AgentExecutor
from aios.agents.models import AgentResult, ExecutionOutcome, ExecutionRequest
from aios.core.task import Task

__all__ = [
    "Agent",
    "AgentResult",
    "AgentExecutor",
    "ExecutionRequest",
    "ExecutionOutcome",
    "Task",
]


@runtime_checkable
class Agent(Protocol):
    name: str
    required_capabilities: list[str]
    required_skills: list[str]

    def execute(self, task: Task, context) -> AgentResult: ...
