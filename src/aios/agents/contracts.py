"""Agent execution contracts — the single interface shared by every agent.

Every agent implements ``execute(task, context) -> AgentResult``. This module
defines the contract vocabulary:

- ``AgentTask`` — the canonical input base.
- ``AgentResult`` (models) — the canonical output base.
- ``AgentError`` — the standardized error with a stable error code.
- ``AgentCapabilities`` — the declared permissions of an agent.
- ``AgentMetadata`` — name, version, timeout, and retry policy.
- ``AgentExecutionEvent`` — the standardized lifecycle event payload.

No agent may return "loose" free-text output outside the contract: structured
results always travel inside an ``AgentResult``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aios.core.task import Task

# ---------------------------------------------------------------------------
# Error codes
# ---------------------------------------------------------------------------

VALIDATION_ERROR = "VALIDATION_ERROR"
RUNTIME_ERROR = "RUNTIME_ERROR"
PERMISSION_DENIED = "PERMISSION_DENIED"
TIMEOUT = "TIMEOUT"
CANCELLED = "CANCELLED"
UNKNOWN = "UNKNOWN"

ERROR_CODES = (
    VALIDATION_ERROR,
    RUNTIME_ERROR,
    PERMISSION_DENIED,
    TIMEOUT,
    CANCELLED,
    UNKNOWN,
)

# ---------------------------------------------------------------------------
# Lifecycle states
# ---------------------------------------------------------------------------

STATE_CREATED = "created"
STATE_VALIDATED = "validated"
STATE_QUEUED = "queued"
STATE_RUNNING = "running"
STATE_SUCCEEDED = "succeeded"
STATE_FAILED = "failed"
STATE_TIMED_OUT = "timed_out"
STATE_CANCELLED = "cancelled"

# ---------------------------------------------------------------------------
# Capability strings
# ---------------------------------------------------------------------------

FILESYSTEM_READ = "filesystem_read"
FILESYSTEM_WRITE = "filesystem_write"
SHELL = "shell"
GIT = "git"
INTERNET = "internet"
ASK_USER = "ask_user"


class AgentValidationError(Exception):
    """Raised when an ``AgentTask`` violates the input contract."""


def coerce_task(task: Task | AgentTask) -> AgentTask:
    """Return an ``AgentTask`` regardless of whether a Task or AgentTask arrives."""
    if isinstance(task, AgentTask):
        return task
    from aios.core.task import Task  # noqa: PLC0415 - local import breaks the core<->agents cycle

    if isinstance(task, Task):
        return AgentTask.from_task(task)
    raise TypeError(f"expected Task or AgentTask, got {type(task).__name__}")


@dataclass
class AgentTask:
    """Canonical agent input."""

    description: str = ""
    task_type: str = "code"
    files: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str = ""

    @classmethod
    def from_task(cls, task: Task | AgentTask, **overrides) -> AgentTask:
        """Build an AgentTask from a scheduler Task, applying any overrides."""
        if isinstance(task, AgentTask):
            for key, value in overrides.items():
                setattr(task, key, value)
            return task
        from aios.core.task import (  # noqa: PLC0415 - local import breaks the core<->agents cycle
            Task,
        )

        if not isinstance(task, Task):
            raise TypeError(f"expected Task or AgentTask, got {type(task).__name__}")
        return cls(
            description=task.description,
            task_type=task.task_type,
            files=list(task.files),
            **overrides,
        )

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "task_type": self.task_type,
            "files": list(self.files),
            "params": dict(self.params),
            "correlation_id": self.correlation_id,
        }


def validate_agent_task(task: AgentTask) -> list[str]:
    """Return a list of contract violations. An empty list means valid."""
    errors: list[str] = []
    if not task.description.strip():
        errors.append("description is required")
    if not task.task_id:
        errors.append("task_id is required")
    return errors


@dataclass(frozen=True)
class AgentError:
    """Standardized error. ``transient`` marks retry-eligible failures."""

    code: str = RUNTIME_ERROR
    message: str = ""
    transient: bool = False

    @property
    def retryable(self) -> bool:
        return self.transient

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "transient": self.transient,
            "retryable": self.retryable,
        }


def error_from_exception(exc: Exception) -> AgentError:
    """Map an exception to the standardized AgentError."""
    if isinstance(exc, AgentValidationError):
        return AgentError(code=VALIDATION_ERROR, message=str(exc), transient=False)
    if isinstance(exc, PermissionError):
        return AgentError(code=PERMISSION_DENIED, message=str(exc), transient=False)
    if isinstance(exc, TimeoutError):
        return AgentError(code=TIMEOUT, message=str(exc), transient=True)
    return AgentError(code=RUNTIME_ERROR, message=str(exc), transient=True)


@dataclass(frozen=True)
class AgentCapabilities:
    """Declared permissions of an agent."""

    permissions: tuple[str, ...] = ()

    @classmethod
    def from_list(cls, permissions: list[str]) -> AgentCapabilities:
        return cls(permissions=tuple(dict.fromkeys(permissions)))

    def has(self, permission: str) -> bool:
        return permission in self.permissions

    @property
    def is_read_only(self) -> bool:
        return not any(
            permission in self.permissions
            for permission in (FILESYSTEM_WRITE, SHELL, GIT, INTERNET)
        )


@dataclass(frozen=True)
class RetryPolicy:
    """Centralized retry policy. ``max_attempts=1`` means no retry."""

    max_attempts: int = 1
    base_delay: float = 0.5
    retryable_codes: tuple[str, ...] = (RUNTIME_ERROR, TIMEOUT)

    @property
    def enabled(self) -> bool:
        return self.max_attempts > 1


@dataclass(frozen=True)
class AgentMetadata:
    """Static metadata every agent declares about itself."""

    name: str
    version: str = "1.0"
    timeout: float | None = None
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    description: str = ""
    allow_timeout_override: bool = False
    allow_retry_override: bool = False


@dataclass(frozen=True)
class AgentExecutionEvent:
    """Standardized execution event payload (agent.execution.* topics).

    Every execution event shares these fields. ``sequence`` orders events
    within a single execution; ``attempt`` identifies the execution attempt;
    ``executor_id`` identifies which AgentExecutor instance ran it.
    """

    event_id: str = ""
    agent: str = ""
    task_id: str = ""
    correlation_id: str = ""
    executor_id: str = ""
    sequence: int = 1
    status: str = ""
    duration_ms: float | None = None
    error_code: str | None = None
    attempt: int = 1
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "agent": self.agent,
            "task_id": self.task_id,
            "correlation_id": self.correlation_id,
            "executor_id": self.executor_id,
            "sequence": self.sequence,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "error_code": self.error_code,
            "attempt": self.attempt,
            "message": self.message,
        }


@dataclass(frozen=True)
class AgentLifecycleEvent:
    """Standardized lifecycle transition payload (agent.lifecycle.changed).

    ``created -> created`` is the initialization event, not a state
    transition: it is emitted once per execution so every timeline has a
    complete, deterministic sequence starting at 1.
    """

    event_id: str = ""
    agent: str = ""
    task_id: str = ""
    correlation_id: str = ""
    executor_id: str = ""
    sequence: int = 1
    status: str = ""
    previous_state: str = ""
    current_state: str = ""

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "agent": self.agent,
            "task_id": self.task_id,
            "correlation_id": self.correlation_id,
            "executor_id": self.executor_id,
            "sequence": self.sequence,
            "status": self.status,
            "previous_state": self.previous_state,
            "current_state": self.current_state,
        }


@dataclass(frozen=True)
class ProgressCallback:
    """Optional progress hook carried by an ExecutionRequest."""

    handler: Callable[[str], None]
