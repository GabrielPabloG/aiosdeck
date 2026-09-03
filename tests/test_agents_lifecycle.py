"""Tests for AgentLifecycle — the execution state machine and duration tracking."""

import pytest

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
from aios.agents.lifecycle import TERMINAL_STATES, AgentLifecycle, LifecycleError


def test_transition_to_validated_sets_state():
    lifecycle = AgentLifecycle()
    lifecycle.transition(STATE_VALIDATED)
    assert lifecycle.state == STATE_VALIDATED


def test_invalid_transition_raises():
    """A jump over intermediate states must raise a LifecycleError."""
    lifecycle = AgentLifecycle()
    with pytest.raises(LifecycleError):
        lifecycle.transition(STATE_RUNNING)


def test_terminal_state_is_immutable():
    """No transition may leave a terminal state."""
    for state in TERMINAL_STATES:
        lifecycle = AgentLifecycle(state=state)
        with pytest.raises(LifecycleError):
            lifecycle.transition(STATE_RUNNING)


def test_created_is_not_a_terminal_state():
    assert STATE_CREATED not in TERMINAL_STATES


def test_transition_to_running_records_start():
    lifecycle = AgentLifecycle()
    lifecycle.transition(STATE_VALIDATED)
    lifecycle.transition(STATE_QUEUED)
    lifecycle.transition(STATE_RUNNING)
    assert lifecycle.started_at is not None


def test_transition_to_terminal_records_finish():
    lifecycle = AgentLifecycle()
    lifecycle.transition(STATE_VALIDATED)
    lifecycle.transition(STATE_QUEUED)
    lifecycle.transition(STATE_RUNNING)
    lifecycle.transition(STATE_SUCCEEDED)
    assert lifecycle.finished_at is not None


def test_duration_is_none_before_start():
    lifecycle = AgentLifecycle()
    assert lifecycle.duration_ms is None


def test_duration_uses_finished_at_when_available():
    lifecycle = AgentLifecycle()
    lifecycle.started_at = 10.0
    lifecycle.finished_at = 10.5
    assert lifecycle.duration_ms == pytest.approx(500.0)


def test_duration_uses_now_when_unfinished():
    lifecycle = AgentLifecycle()
    lifecycle.started_at = 10.0
    lifecycle.finished_at = None
    assert lifecycle.duration_ms is not None
    assert lifecycle.duration_ms >= 0.0


def test_to_dict_carries_all_fields():
    lifecycle = AgentLifecycle()
    lifecycle.transition(STATE_VALIDATED)
    payload = lifecycle.to_dict()
    assert payload["state"] == STATE_VALIDATED
    assert "started_at" in payload
    assert "finished_at" in payload
    assert "duration_ms" in payload


def test_running_to_running_is_allowed_on_retry():
    lifecycle = AgentLifecycle(state=STATE_RUNNING, started_at=5.0)
    lifecycle.transition(STATE_RUNNING)
    assert lifecycle.state == STATE_RUNNING
    assert lifecycle.started_at == 5.0


def test_failed_and_timed_out_are_terminal():
    assert STATE_FAILED in TERMINAL_STATES
    assert STATE_TIMED_OUT in TERMINAL_STATES
    assert STATE_CANCELLED in TERMINAL_STATES
