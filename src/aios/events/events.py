"""Event type definitions."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class Event:
    topic: str
    payload: Any = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    correlation_id: str = ""


SYSTEM_TOPICS = [
    "system.health_check",
    "system.error",
    "system.shutdown",
]

SESSION_TOPICS = [
    "session.start",
    "session.ready",
    "session.shutdown",
]

CONTEXT_TOPICS = [
    "context.detected",
    "context.error",
]

MEMORY_TOPICS = [
    "memory.loaded",
    "memory.updated",
    "memory.error",
]

TASK_TOPICS = [
    "task.created",
    "task.dispatched",
    "task.completed",
    "task.failed",
    "task.retrying",
]

AGENT_TOPICS = [
    "agent.started",
    "agent.completed",
    "agent.errored",
    "agent.skill_loaded",
]

QUALITY_TOPICS = [
    "quality.started",
    "quality.gate_passed",
    "quality.gate_failed",
    "quality.completed",
]

SECURITY_TOPICS = [
    "security.violation",
    "security.approval_requested",
    "security.approval_granted",
    "security.approval_denied",
]

WORKFLOW_TOPICS = [
    "workflow.started",
    "workflow.stage_changed",
    "workflow.completed",
    "workflow.failed",
]

RUNTIME_TOPICS = [
    "runtime.ready",
    "runtime.error",
    "runtime.disconnected",
]

ALL_TOPICS = (
    SYSTEM_TOPICS
    + SESSION_TOPICS
    + CONTEXT_TOPICS
    + MEMORY_TOPICS
    + TASK_TOPICS
    + AGENT_TOPICS
    + QUALITY_TOPICS
    + SECURITY_TOPICS
    + WORKFLOW_TOPICS
    + RUNTIME_TOPICS
)
