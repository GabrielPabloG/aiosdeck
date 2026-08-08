"""Tests for AgentExecutor — the single execution boundary.

Covers validation, capability enforcement, lifecycle status, timeout, retry,
cancellation, the two-tier lifecycle/execution events, and the standardized
event payload (event_id, sequence, executor_id, correlation/task IDs).
"""

import threading
import time
from unittest.mock import MagicMock

from aios.agents.contracts import (
    PERMISSION_DENIED,
    RUNTIME_ERROR,
    STATE_CREATED,
    STATE_FAILED,
    STATE_QUEUED,
    STATE_RUNNING,
    STATE_SUCCEEDED,
    STATE_VALIDATED,
    TIMEOUT,
    VALIDATION_ERROR,
    AgentCapabilities,
    AgentMetadata,
    AgentTask,
    RetryPolicy,
)
from aios.agents.executor import AgentExecutor, make_request
from aios.agents.models import AgentResult
from aios.events.events import (
    AGENT_EXECUTION_COMPLETED,
    AGENT_EXECUTION_RETRIED,
    AGENT_EXECUTION_STARTED,
    AGENT_EXECUTION_TIMED_OUT,
    AGENT_LIFECYCLE_CHANGED,
)


class _FakeAgent:
    name = "fake"

    def __init__(self, fn=None, timeout=None, retry_policy=None):
        self._fn = fn or (lambda task, context: AgentResult(success=True, output="ok"))
        self.metadata = AgentMetadata(
            name=self.name,
            timeout=timeout,
            retry_policy=retry_policy or RetryPolicy(),
        )
        self.capabilities = AgentCapabilities.from_list(["filesystem_read"])

    def execute(self, task, context):
        return self._fn(task, context)


def _task() -> AgentTask:
    return AgentTask(description="do something")


def test_execute_success():
    executor = AgentExecutor()
    outcome = executor.execute(make_request(_FakeAgent(), _task()))
    assert outcome.status == STATE_SUCCEEDED
    assert outcome.result is not None
    assert outcome.result.success is True
    assert outcome.result.output == "ok"
    assert outcome.duration_ms >= 0
    assert outcome.attempts == 1
    assert outcome.retried is False


def test_execute_error_maps_to_agent_error():
    def boom(task, context):
        raise RuntimeError("boom")

    executor = AgentExecutor()
    outcome = executor.execute(make_request(_FakeAgent(fn=boom), _task()))
    assert outcome.status == STATE_FAILED
    assert outcome.error is not None
    assert outcome.error.code == RUNTIME_ERROR
    assert "boom" in outcome.error.message


def test_execute_timeout_fires():
    executor = AgentExecutor()
    request = make_request(
        _FakeAgent(fn=lambda task, context: time.sleep(2), timeout=0.1),
        _task(),
    )
    outcome = executor.execute(request)
    assert outcome.status == "timed_out"
    assert outcome.error is not None
    assert outcome.error.code == TIMEOUT


def test_execute_no_timeout_runs_directly():
    executor = AgentExecutor()
    outcome = executor.execute(make_request(_FakeAgent(timeout=None), _task()))
    assert outcome.status == STATE_SUCCEEDED
    assert outcome.result.output == "ok"


def test_event_bus_on_success():
    bus = MagicMock()
    executor = AgentExecutor(event_bus=bus)
    executor.execute(make_request(_FakeAgent(), _task()))
    calls = [c.args[0] for c in bus.publish.call_args_list]
    assert AGENT_EXECUTION_STARTED in calls
    assert AGENT_EXECUTION_COMPLETED in calls
    assert AGENT_LIFECYCLE_CHANGED in calls


def test_lifecycle_changed_transition_sequence():
    """agent.lifecycle.changed carries previous_state/current_state for every hop."""
    bus = MagicMock()
    executor = AgentExecutor(event_bus=bus)
    request = make_request(_FakeAgent(), _task())
    executor.execute(request)

    lifecycle = [
        c.args[1] for c in bus.publish.call_args_list if c.args[0] == AGENT_LIFECYCLE_CHANGED
    ]
    hops = [(event["previous_state"], event["current_state"]) for event in lifecycle]
    assert hops == [
        (STATE_CREATED, STATE_CREATED),  # initialization event
        (STATE_CREATED, STATE_VALIDATED),
        (STATE_VALIDATED, STATE_QUEUED),
        (STATE_QUEUED, STATE_RUNNING),
        (STATE_RUNNING, STATE_SUCCEEDED),
    ]


def test_event_payload_is_standardized():
    bus = MagicMock()
    executor = AgentExecutor(event_bus=bus)
    request = make_request(_FakeAgent(), _task(), correlation_id="corr-1")
    executor.execute(request)

    completed = [
        c.args[1] for c in bus.publish.call_args_list if c.args[0] == AGENT_EXECUTION_COMPLETED
    ]
    payload = completed[0]
    assert payload["agent"] == "fake"
    assert payload["task_id"] == request.task.task_id
    assert payload["correlation_id"] == "corr-1"
    assert payload["status"] == STATE_SUCCEEDED
    assert payload["duration_ms"] >= 0
    assert payload["error_code"] is None
    assert payload["attempt"] == 1
    assert payload["event_id"]
    assert payload["executor_id"] == executor.executor_id
    assert payload["sequence"] >= 1


def test_sequence_is_monotonic_per_execution():
    bus = MagicMock()
    executor = AgentExecutor(event_bus=bus)
    executor.execute(make_request(_FakeAgent(), _task()))

    sequences = [c.args[1]["sequence"] for c in bus.publish.call_args_list]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)  # unique per event


def test_event_bus_on_timeout():
    bus = MagicMock()
    executor = AgentExecutor(event_bus=bus)
    request = make_request(
        _FakeAgent(fn=lambda task, context: time.sleep(2), timeout=0.1),
        _task(),
    )
    executor.execute(request)
    calls = [c.args[0] for c in bus.publish.call_args_list]
    assert AGENT_EXECUTION_TIMED_OUT in calls


def test_retry_transient_error():
    calls = {"n": 0}

    def flaky(task, context):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("connection lost")
        return AgentResult(success=True, output="recovered")

    policy = RetryPolicy(max_attempts=2, base_delay=0.0, retryable_codes=(RUNTIME_ERROR,))
    executor = AgentExecutor()
    outcome = executor.execute(make_request(_FakeAgent(fn=flaky, retry_policy=policy), _task()))
    assert outcome.status == STATE_SUCCEEDED
    assert outcome.result.output == "recovered"
    assert outcome.attempts == 2  # noqa: PLR2004
    assert outcome.retried is True


def test_retry_default_is_no_retry():
    def always_fail(task, context):
        raise RuntimeError("boom")

    executor = AgentExecutor()
    outcome = executor.execute(make_request(_FakeAgent(fn=always_fail), _task()))
    assert outcome.status == STATE_FAILED
    assert outcome.attempts == 1
    assert outcome.retried is False


def test_retry_emits_retried_event():
    calls = {"n": 0}
    bus = MagicMock()

    def flaky(task, context):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("connection lost")
        return AgentResult(success=True, output="recovered")

    policy = RetryPolicy(max_attempts=2, base_delay=0.0, retryable_codes=(RUNTIME_ERROR,))
    executor = AgentExecutor(event_bus=bus)
    executor.execute(make_request(_FakeAgent(fn=flaky, retry_policy=policy), _task()))
    calls_topics = [c.args[0] for c in bus.publish.call_args_list]
    assert AGENT_EXECUTION_RETRIED in calls_topics
    assert AGENT_EXECUTION_COMPLETED in calls_topics


def test_retry_attempt_is_distinct_from_sequence():
    calls = {"n": 0}
    bus = MagicMock()

    def flaky(task, context):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("connection lost")
        return AgentResult(success=True, output="recovered")

    policy = RetryPolicy(max_attempts=2, base_delay=0.0, retryable_codes=(RUNTIME_ERROR,))
    executor = AgentExecutor(event_bus=bus)
    executor.execute(make_request(_FakeAgent(fn=flaky, retry_policy=policy), _task()))

    started = [
        c.args[1] for c in bus.publish.call_args_list if c.args[0] == AGENT_EXECUTION_STARTED
    ]
    assert [event["attempt"] for event in started] == [1, 2]  # noqa: PLR2004
    assert started[0]["sequence"] != started[1]["sequence"]


def test_validation_error():
    executor = AgentExecutor()
    outcome = executor.execute(make_request(_FakeAgent(), AgentTask(description="")))
    assert outcome.status == STATE_FAILED
    assert outcome.error is not None
    assert outcome.error.code == VALIDATION_ERROR


def test_permission_denied():
    class DenyEnforcer:
        def validate(self, agent):
            raise PermissionError("capability denied")

    executor = AgentExecutor(capabilities_enforcer=DenyEnforcer())
    outcome = executor.execute(make_request(_FakeAgent(), _task()))
    assert outcome.status == STATE_FAILED
    assert outcome.error is not None
    assert outcome.error.code == PERMISSION_DENIED


def test_cancellation():
    executor = AgentExecutor()
    result_holder: list = []

    def flaky(task, context):
        raise RuntimeError("connection lost")

    policy = RetryPolicy(max_attempts=5, base_delay=1.0, retryable_codes=(RUNTIME_ERROR,))
    request = make_request(_FakeAgent(fn=flaky, retry_policy=policy), _task())

    def run():
        result_holder.append(executor.execute(request))

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.3)
    executor.cancel()
    thread.join(timeout=4)
    assert result_holder
    assert result_holder[0].status == "cancelled"
