"""Agent execution lifecycle — a validated state machine.

States: created → validated → queued → running →
        succeeded | failed | timed_out | cancelled.

Notes:
- ``created -> created`` is the **initialization event**, not a state
  transition: the executor emits one ``agent.lifecycle.changed`` with
  previous=current=created so every execution has a complete, deterministic
  sequence starting at 1. It is not part of the transition map.
- ``running -> running`` is allowed on a centralized retry; it never resets
  the clock.
- Terminal states are immutable: no transitions out.
"""

import time
from dataclasses import dataclass

from aios.agents.contracts import (
    STATE_CANCELLED,
    STATE_CREATED,
    STATE_FAILED,
    STATE_QUEUED,
    STATE_RUNNING,
    STATE_SUCCEEDED,
    STATE_TIMED_OUT,
    STATE_VALIDATED,
)

TERMINAL_STATES = {STATE_SUCCEEDED, STATE_FAILED, STATE_TIMED_OUT, STATE_CANCELLED}

_TRANSITIONS: dict[str, set[str]] = {
    STATE_CREATED: {STATE_VALIDATED, STATE_FAILED, STATE_CANCELLED},
    STATE_VALIDATED: {STATE_QUEUED, STATE_FAILED, STATE_CANCELLED},
    STATE_QUEUED: {STATE_RUNNING, STATE_FAILED, STATE_CANCELLED},
    STATE_RUNNING: {
        STATE_SUCCEEDED,
        STATE_FAILED,
        STATE_TIMED_OUT,
        STATE_CANCELLED,
        STATE_RUNNING,
    },
    STATE_SUCCEEDED: set(),
    STATE_FAILED: set(),
    STATE_TIMED_OUT: set(),
    STATE_CANCELLED: set(),
}


class LifecycleError(Exception):
    """Raised on an invalid state transition."""


@dataclass
class AgentLifecycle:
    """Tracks one execution's state and duration. Not thread-safe by design."""

    state: str = STATE_CREATED
    started_at: float | None = None
    finished_at: float | None = None

    def transition(self, next_state: str) -> None:
        if next_state not in _TRANSITIONS.get(self.state, set()):
            raise LifecycleError(f"Invalid transition: {self.state} -> {next_state}")
        self.state = next_state
        if next_state == STATE_RUNNING and self.started_at is None:
            self.started_at = time.monotonic()
        if next_state in TERMINAL_STATES:
            self.finished_at = time.monotonic()

    @property
    def duration_ms(self) -> float | None:
        if self.started_at is None:
            return None
        end = self.finished_at or time.monotonic()
        return (end - self.started_at) * 1000

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
        }
