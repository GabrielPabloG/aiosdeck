"""Agent execution models — request, outcome, result."""

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class ExecutionRequest:
    invoke: Callable[[], str]


@dataclass(kw_only=True)
class ExecutionOutcome:
    output: str
    duration_ms: float = 0.0
    error: Exception | None = None


@dataclass
class AgentResult:
    success: bool = True
    output: str = ""
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
