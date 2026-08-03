"""Tests for AgentExecutor — timeout, error handling, event bus."""

import time
from concurrent.futures import TimeoutError
from unittest.mock import MagicMock

from aios.agents.executor import AgentExecutor
from aios.agents.models import ExecutionOutcome, ExecutionRequest
from aios.events.events import (
    AGENT_EXECUTION_FAILED,
    AGENT_EXECUTION_FINISHED,
    AGENT_EXECUTION_STARTED,
)


def test_execute_success():
    executor = AgentExecutor()
    request = ExecutionRequest(invoke=lambda: "hello")
    outcome = executor.execute(request)
    assert isinstance(outcome, ExecutionOutcome)
    assert outcome.output == "hello"
    assert outcome.error is None
    assert outcome.duration_ms >= 0


def test_execute_error():
    executor = AgentExecutor()

    def boom():
        msg = "boom"
        raise RuntimeError(msg)

    request = ExecutionRequest(invoke=boom)
    outcome = executor.execute(request)
    assert outcome.output == ""
    assert outcome.error is not None
    assert "boom" in str(outcome.error)


def test_execute_timeout_fires():
    executor = AgentExecutor()
    request = ExecutionRequest(
        invoke=lambda: time.sleep(2),
        timeout=0.1,
    )
    outcome = executor.execute(request)
    assert outcome.output == ""
    assert outcome.error is not None
    assert isinstance(outcome.error, TimeoutError)


def test_execute_timeout_does_not_interfere():
    executor = AgentExecutor()
    request = ExecutionRequest(
        invoke=lambda: "quick",
        timeout=5,
    )
    outcome = executor.execute(request)
    assert outcome.output == "quick"
    assert outcome.error is None


def test_execute_no_timeout_runs_directly():
    executor = AgentExecutor()
    request = ExecutionRequest(invoke=lambda: "direct")
    outcome = executor.execute(request)
    assert outcome.output == "direct"
    assert outcome.error is None


def test_event_bus_on_success():
    bus = MagicMock()
    executor = AgentExecutor(event_bus=bus)
    request = ExecutionRequest(invoke=lambda: "ok")
    executor.execute(request)
    min_events = 2
    assert bus.publish.call_count >= min_events
    calls = [c.args[0] for c in bus.publish.call_args_list]
    assert AGENT_EXECUTION_STARTED in calls
    assert AGENT_EXECUTION_FINISHED in calls


def test_event_bus_on_timeout():
    bus = MagicMock()
    executor = AgentExecutor(event_bus=bus)
    request = ExecutionRequest(invoke=lambda: time.sleep(2), timeout=0.1)
    executor.execute(request)
    calls = [c.args[0] for c in bus.publish.call_args_list]
    assert AGENT_EXECUTION_FAILED in calls
