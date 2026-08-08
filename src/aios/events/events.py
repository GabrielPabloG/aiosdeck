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

AGENT_LIFECYCLE_TOPICS = [
    "agent.lifecycle.changed",
]

AGENT_EXECUTION_TOPICS = [
    "agent.execution.started",
    "agent.execution.progress",
    "agent.execution.completed",
    "agent.execution.failed",
    "agent.execution.timed_out",
    "agent.execution.retried",
    "agent.execution.cancelled",
]

AGENT_LIFECYCLE_CHANGED = "agent.lifecycle.changed"

AGENT_EXECUTION_STARTED = "agent.execution.started"
AGENT_EXECUTION_PROGRESS = "agent.execution.progress"
AGENT_EXECUTION_COMPLETED = "agent.execution.completed"
AGENT_EXECUTION_FAILED = "agent.execution.failed"
AGENT_EXECUTION_TIMED_OUT = "agent.execution.timed_out"
AGENT_EXECUTION_RETRIED = "agent.execution.retried"
AGENT_EXECUTION_CANCELLED = "agent.execution.cancelled"

KANBAN_TOPICS = [
    "kanban.card_moved",
    "kanban.card_blocked",
    "kanban.subtask_created",
    "kanban.subtask_completed",
]

KANBAN_CARD_MOVED = "kanban.card_moved"
KANBAN_CARD_BLOCKED = "kanban.card_blocked"
KANBAN_SUBTASK_CREATED = "kanban.subtask_created"
KANBAN_SUBTASK_COMPLETED = "kanban.subtask_completed"

QUALITY_TOPICS = [
    "quality.started",
    "quality.gate_started",
    "quality.gate_completed",
    "quality.gate_blocked",
    "quality.gate_passed",
    "quality.gate_failed",
    "quality.completed",
]

QUALITY_STARTED = "quality.started"
QUALITY_GATE_STARTED = "quality.gate_started"
QUALITY_GATE_COMPLETED = "quality.gate_completed"
QUALITY_GATE_BLOCKED = "quality.gate_blocked"
QUALITY_GATE_PASSED = "quality.gate_passed"
QUALITY_GATE_FAILED = "quality.gate_failed"
QUALITY_COMPLETED = "quality.completed"

SECURITY_TOPICS = [
    "security.violation",
    "security.approval_requested",
    "security.approval_granted",
    "security.approval_denied",
    "security.intent.applied",
    "security.check.passed",
    "security.check.denied",
]

SECURITY_INTENT_APPLIED = "security.intent.applied"
SECURITY_CHECK_PASSED = "security.check.passed"
SECURITY_CHECK_DENIED = "security.check.denied"

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
    "runtime.route_selected",
]

RUNTIME_READY = "runtime.ready"
RUNTIME_ERROR = "runtime.error"
RUNTIME_DISCONNECTED = "runtime.disconnected"
RUNTIME_ROUTE_SELECTED = "runtime.route_selected"

TELEMETRY_TOPICS = [
    "telemetry.usage.captured",
    "telemetry.cost.calculated",
]

RESEARCH_TOPICS = [
    "research.completed",
]

LEARNING_TOPICS = [
    "learning.observation_recorded",
    "learning.candidate.created",
    "learning.candidate.approved",
    "learning.candidate.rejected",
    "learning.ingested",
]

RESEARCH_COMPLETED = "research.completed"
LEARNING_OBSERVATION_RECORDED = "learning.observation_recorded"
LEARNING_CANDIDATE_CREATED = "learning.candidate.created"
LEARNING_CANDIDATE_APPROVED = "learning.candidate.approved"
LEARNING_CANDIDATE_REJECTED = "learning.candidate.rejected"
LEARNING_INGESTED = "learning.ingested"

ALL_TOPICS = (
    SYSTEM_TOPICS
    + SESSION_TOPICS
    + CONTEXT_TOPICS
    + MEMORY_TOPICS
    + TASK_TOPICS
    + AGENT_LIFECYCLE_TOPICS
    + AGENT_EXECUTION_TOPICS
    + KANBAN_TOPICS
    + QUALITY_TOPICS
    + SECURITY_TOPICS
    + WORKFLOW_TOPICS
    + RUNTIME_TOPICS
    + TELEMETRY_TOPICS
    + RESEARCH_TOPICS
    + LEARNING_TOPICS
)
