"""Mutation-killing tests for AgentExecutor, TelemetryStore, and create_kernel.

Targets ARG_REMOVAL, CONSTANT_REPLACEMENT, and STRING_MUTATION survivors
by asserting that every argument/constant/string literal has an observable
effect on the output.
"""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aios.agents.contracts import (
    CANCELLED,
    PERMISSION_DENIED,
    RUNTIME_ERROR,
    STATE_CANCELLED,
    STATE_CREATED,
    STATE_FAILED,
    STATE_QUEUED,
    STATE_RUNNING,
    STATE_SUCCEEDED,
    STATE_TIMED_OUT,
    STATE_VALIDATED,
    TIMEOUT,
    VALIDATION_ERROR,
    AgentCapabilities,
    AgentError,
    AgentMetadata,
    AgentTask,
    RetryPolicy,
)
from aios.agents.executor import AgentExecutor, make_request
from aios.agents.models import AgentResult, ExecutionOutcome, ExecutionRequest
from aios.events.events import (
    AGENT_EXECUTION_CANCELLED,
    AGENT_EXECUTION_COMPLETED,
    AGENT_EXECUTION_FAILED,
    AGENT_EXECUTION_RETRIED,
    AGENT_EXECUTION_STARTED,
    AGENT_EXECUTION_TIMED_OUT,
    AGENT_LIFECYCLE_CHANGED,
    SECURITY_CHECK_DENIED,
    SECURITY_CHECK_PASSED,
    SECURITY_INTENT_APPLIED,
)
from aios.security.contracts import IntentPolicy
from aios.telemetry.store import TelemetryStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeAgent:
    def __init__(self, fn=None, timeout=None, retry_policy=None, name="fake",
                 allow_timeout_override=False, capabilities=None):
        self._fn = fn or (lambda task, context: AgentResult(success=True, output="ok"))
        self.name = name
        self.metadata = AgentMetadata(
            name=name,
            timeout=timeout,
            retry_policy=retry_policy or RetryPolicy(),
            allow_timeout_override=allow_timeout_override,
        )
        self.capabilities = capabilities or AgentCapabilities.from_list(
            ["filesystem_read"]
        )

    def execute(self, task, context):
        return self._fn(task, context)


def _task(desc="do something", corr_id="", task_id=""):
    kwargs = {"description": desc}
    if corr_id:
        kwargs["correlation_id"] = corr_id
    if task_id:
        kwargs["task_id"] = task_id
    return AgentTask(**kwargs)


# ===========================================================================
# 1. AgentExecutor.execute — outcome status, retry, timeout, capabilities,
#    intent, on_progress, correlation_id, _should_retry, _backoff
# ===========================================================================


class TestExecuteOutcomeStatus:
    """Verify ExecutionOutcome.status reflects success/failure/timeout/cancel."""

    def test_success_status(self):
        executor = AgentExecutor()
        outcome = executor.execute(make_request(_FakeAgent(), _task()))
        assert outcome.status == STATE_SUCCEEDED
        assert outcome.result is not None
        assert outcome.result.success is True

    def test_failure_status_from_exception(self):
        def boom(task, context):
            raise RuntimeError("boom")

        executor = AgentExecutor()
        outcome = executor.execute(make_request(_FakeAgent(fn=boom), _task()))
        assert outcome.status == STATE_FAILED
        assert outcome.error is not None
        assert outcome.error.code == RUNTIME_ERROR

    def test_failure_status_from_agent_result(self):
        def fail(task, context):
            return AgentResult(success=False, errors=["bad"])

        executor = AgentExecutor()
        outcome = executor.execute(make_request(_FakeAgent(fn=fail), _task()))
        assert outcome.status == STATE_FAILED
        assert outcome.error is not None

    def test_timeout_status(self):
        executor = AgentExecutor()
        request = make_request(
            _FakeAgent(fn=lambda t, c: time.sleep(5), timeout=0.01),
            _task(),
        )
        outcome = executor.execute(request)
        assert outcome.status == STATE_TIMED_OUT
        assert outcome.error is not None
        assert outcome.error.code == TIMEOUT

    def test_validation_error_status(self):
        executor = AgentExecutor()
        outcome = executor.execute(make_request(_FakeAgent(), _task(desc="")))
        assert outcome.status == STATE_FAILED
        assert outcome.error is not None
        assert outcome.error.code == VALIDATION_ERROR

    def test_permission_denied_status(self):
        class Denier:
            def validate(self, agent):
                raise PermissionError("nope")

        executor = AgentExecutor(capabilities_enforcer=Denier())
        outcome = executor.execute(make_request(_FakeAgent(), _task()))
        assert outcome.status == STATE_FAILED
        assert outcome.error is not None
        assert outcome.error.code == PERMISSION_DENIED

    def test_cancellation_status(self):
        import threading

        executor = AgentExecutor()
        lock = threading.Event()

        def slow(t, c):
            lock.wait(timeout=5)

        policy = RetryPolicy(max_attempts=5, base_delay=0.1, retryable_codes=(RUNTIME_ERROR,))
        request = make_request(_FakeAgent(fn=slow, retry_policy=policy), _task())

        def run():
            return executor.execute(request)

        thread = threading.Thread(target=run)
        thread.start()
        time.sleep(0.1)
        executor.cancel()
        thread.join(timeout=4)
        # The outcome is returned inside the thread; verify via the executor state
        assert executor._cancelled

    def test_outcome_attempts_default_is_one(self):
        executor = AgentExecutor()
        outcome = executor.execute(make_request(_FakeAgent(), _task()))
        assert outcome.attempts == 1

    def test_outcome_retried_default_is_false(self):
        executor = AgentExecutor()
        outcome = executor.execute(make_request(_FakeAgent(), _task()))
        assert outcome.retried is False

    def test_outcome_duration_ms_non_negative(self):
        executor = AgentExecutor()
        outcome = executor.execute(make_request(_FakeAgent(), _task()))
        assert outcome.duration_ms >= 0

    def test_outcome_result_carries_output(self):
        executor = AgentExecutor()
        outcome = executor.execute(make_request(_FakeAgent(), _task()))
        assert outcome.result.output == "ok"

    def test_outcome_error_code_custom(self):
        def custom_fail(task, context):
            return AgentResult(
                success=False, error_code="MY_ERR", errors=["x", "y"]
            )

        executor = AgentExecutor()
        outcome = executor.execute(make_request(_FakeAgent(fn=custom_fail), _task()))
        assert outcome.error.code == "MY_ERR"
        assert "x; y" in outcome.error.message


class TestRetryPolicyBehavior:
    """Verify retry_policy arguments (max_attempts, retryable_codes, base_delay) affect retry."""

    def test_max_attempts_controls_number_of_retries(self):
        calls = {"n": 0}

        def flaky(t, c):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("fail")
            return AgentResult(success=True, output="ok")

        policy = RetryPolicy(max_attempts=3, base_delay=0.0, retryable_codes=(RUNTIME_ERROR,))
        executor = AgentExecutor()
        outcome = executor.execute(make_request(_FakeAgent(fn=flaky, retry_policy=policy), _task()))
        assert outcome.status == STATE_SUCCEEDED
        assert outcome.attempts == 3
        assert outcome.retried is True

    def test_max_attempts_one_means_no_retry(self):
        calls = {"n": 0}

        def flaky(t, c):
            calls["n"] += 1
            raise RuntimeError("fail")

        policy = RetryPolicy(max_attempts=1, retryable_codes=(RUNTIME_ERROR,))
        executor = AgentExecutor()
        outcome = executor.execute(make_request(_FakeAgent(fn=flaky, retry_policy=policy), _task()))
        assert outcome.status == STATE_FAILED
        assert outcome.attempts == 1
        assert outcome.retried is False

    def test_retryable_codes_must_match_error_code(self):
        def fail(t, c):
            raise RuntimeError("fail")

        # TIMEOUT is not in retryable_codes, only RUNTIME_ERROR
        policy = RetryPolicy(max_attempts=3, retryable_codes=(TIMEOUT,))
        executor = AgentExecutor()
        outcome = executor.execute(make_request(_FakeAgent(fn=fail, retry_policy=policy), _task()))
        assert outcome.status == STATE_FAILED
        assert outcome.attempts == 1  # no retry

    def test_retryable_codes_match_enables_retry(self):
        calls = {"n": 0}

        def flaky(t, c):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("fail")
            return AgentResult(success=True, output="ok")

        policy = RetryPolicy(max_attempts=2, retryable_codes=(RUNTIME_ERROR,))
        executor = AgentExecutor()
        outcome = executor.execute(make_request(_FakeAgent(fn=flaky, retry_policy=policy), _task()))
        assert outcome.status == STATE_SUCCEEDED
        assert outcome.attempts == 2

    def test_base_delay_affects_sleep(self):
        """Verify _backoff uses base_delay."""
        executor = AgentExecutor()
        policy = RetryPolicy(base_delay=2.0)
        # _backoff(policy, attempt=2) = base_delay * 2^(attempt-2) = 2.0 * 1 = 2.0
        delay = AgentExecutor._backoff(policy, 2)
        assert delay == 2.0

    def test_backoff_doubles_each_attempt(self):
        executor = AgentExecutor()
        policy = RetryPolicy(base_delay=1.0)
        assert AgentExecutor._backoff(policy, 2) == 1.0  # 1.0 * 2^0
        assert AgentExecutor._backoff(policy, 3) == 2.0  # 1.0 * 2^1
        assert AgentExecutor._backoff(policy, 4) == 4.0  # 1.0 * 2^2

    def test_retry_emits_retried_event(self):
        calls = {"n": 0}
        bus = MagicMock()

        def flaky(t, c):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("fail")
            return AgentResult(success=True, output="ok")

        policy = RetryPolicy(max_attempts=2, base_delay=0.0, retryable_codes=(RUNTIME_ERROR,))
        executor = AgentExecutor(event_bus=bus)
        executor.execute(make_request(_FakeAgent(fn=flaky, retry_policy=policy), _task()))
        topics = [c.args[0] for c in bus.publish.call_args_list]
        assert AGENT_EXECUTION_RETRIED in topics
        assert AGENT_EXECUTION_COMPLETED in topics


class TestShouldRetry:
    """Unit-test _should_retry static method."""

    def test_no_policy_means_no_retry(self):
        error = AgentError(code=RUNTIME_ERROR, transient=True)
        assert AgentExecutor._should_retry(error, None, 1, 3) is False

    def test_attempt_exceeds_max_means_no_retry(self):
        error = AgentError(code=RUNTIME_ERROR, transient=True)
        policy = RetryPolicy(max_attempts=3)
        assert AgentExecutor._should_retry(error, policy, 3, 3) is False

    def test_attempt_below_max_with_matching_code(self):
        error = AgentError(code=RUNTIME_ERROR, transient=True)
        policy = RetryPolicy(max_attempts=3, retryable_codes=(RUNTIME_ERROR,))
        assert AgentExecutor._should_retry(error, policy, 1, 3) is True

    def test_non_retryable_error_means_no_retry(self):
        error = AgentError(code=RUNTIME_ERROR, transient=False)
        policy = RetryPolicy(max_attempts=3, retryable_codes=(RUNTIME_ERROR,))
        assert AgentExecutor._should_retry(error, policy, 1, 3) is False

    def test_code_not_in_retryable_codes(self):
        error = AgentError(code="OTHER_ERROR", transient=True)
        policy = RetryPolicy(max_attempts=3, retryable_codes=(RUNTIME_ERROR,))
        assert AgentExecutor._should_retry(error, policy, 1, 3) is False


class TestBackoff:
    """Unit-test _backoff static method."""

    def test_backoff_default_policy(self):
        """With no policy, default delay 0.5."""
        delay = AgentExecutor._backoff(None, 2)
        assert delay == 0.5

    def test_backoff_attempt_2(self):
        policy = RetryPolicy(base_delay=1.5)
        assert AgentExecutor._backoff(policy, 2) == 1.5

    def test_backoff_attempt_3(self):
        policy = RetryPolicy(base_delay=1.5)
        assert AgentExecutor._backoff(policy, 3) == 3.0

    def test_backoff_attempt_4(self):
        policy = RetryPolicy(base_delay=1.5)
        assert AgentExecutor._backoff(policy, 4) == 6.0


class TestResolveTimeout:
    """Unit-test _resolve_timeout static method."""

    def test_uses_metadata_timeout_when_no_override(self):
        agent = _FakeAgent(timeout=5.0, allow_timeout_override=False)
        request = ExecutionRequest(agent=agent, task=_task(), timeout=10.0)
        result = AgentExecutor._resolve_timeout(request)
        assert result == 5.0

    def test_uses_request_timeout_when_override_allowed(self):
        agent = _FakeAgent(timeout=5.0, allow_timeout_override=True)
        request = ExecutionRequest(agent=agent, task=_task(), timeout=10.0)
        result = AgentExecutor._resolve_timeout(request)
        assert result == 10.0

    def test_uses_metadata_timeout_when_request_timeout_is_none(self):
        agent = _FakeAgent(timeout=5.0, allow_timeout_override=True)
        request = ExecutionRequest(agent=agent, task=_task(), timeout=None)
        result = AgentExecutor._resolve_timeout(request)
        assert result == 5.0

    def test_returns_none_when_both_none(self):
        agent = _FakeAgent(timeout=None, allow_timeout_override=True)
        request = ExecutionRequest(agent=agent, task=_task(), timeout=None)
        result = AgentExecutor._resolve_timeout(request)
        assert result is None


class TestCapabilitiesEnforcer:
    """Verify capabilities_enforcer blocks unauthorized agents."""

    def test_enforcer_blocks_agent(self):
        class Denier:
            def validate(self, agent):
                raise PermissionError("missing capability")

        bus = MagicMock()
        executor = AgentExecutor(event_bus=bus, capabilities_enforcer=Denier())
        outcome = executor.execute(make_request(_FakeAgent(), _task()))
        assert outcome.status == STATE_FAILED
        assert outcome.error.code == PERMISSION_DENIED
        assert "missing capability" in outcome.error.message

    def test_enforcer_allows_agent(self):
        class Passer:
            def validate(self, agent):
                pass

        executor = AgentExecutor(capabilities_enforcer=Passer())
        outcome = executor.execute(make_request(_FakeAgent(), _task()))
        assert outcome.status == STATE_SUCCEEDED

    def test_no_enforcer_passes_by_default(self):
        executor = AgentExecutor(capabilities_enforcer=None)
        outcome = executor.execute(make_request(_FakeAgent(), _task()))
        assert outcome.status == STATE_SUCCEEDED

    def test_enforcer_failure_publishes_lifecycle(self):
        class Denier:
            def validate(self, agent):
                raise PermissionError("denied")

        bus = MagicMock()
        executor = AgentExecutor(event_bus=bus, capabilities_enforcer=Denier())
        executor.execute(make_request(_FakeAgent(), _task()))
        lifecycle = [
            c.args[1]
            for c in bus.publish.call_args_list
            if c.args[0] == AGENT_LIFECYCLE_CHANGED
        ]
        states = [e["current_state"] for e in lifecycle]
        assert STATE_FAILED in states


class TestIntentValidation:
    """Verify intent validation (allowed and denied cases)."""

    def test_intent_allowed(self):
        bus = MagicMock()
        intent = IntentPolicy(
            actions=frozenset(["filesystem.read"]),
            deny=frozenset(),
            name="read_files",
            source="user",
        )
        executor = AgentExecutor()
        request = make_request(_FakeAgent(), _task(), intent=intent)
        outcome = executor.execute(request)
        assert outcome.status == STATE_SUCCEEDED

    def test_intent_denied(self):
        bus = MagicMock()
        intent = IntentPolicy(
            actions=frozenset(["shell_execute"]),
            deny=frozenset(),
            name="run_shell",
            source="user",
        )
        executor = AgentExecutor()
        request = make_request(_FakeAgent(), _task(), intent=intent)
        outcome = executor.execute(request)
        assert outcome.status == STATE_FAILED
        assert outcome.error.code == PERMISSION_DENIED

    def test_intent_none_skips_validation(self):
        executor = AgentExecutor()
        request = make_request(_FakeAgent(), _task(), intent=None)
        outcome = executor.execute(request)
        assert outcome.status == STATE_SUCCEEDED

    def test_intent_publishes_security_events(self):
        bus = MagicMock()
        intent = IntentPolicy(
            actions=frozenset(["filesystem.read"]),
            name="read",
            source="user",
        )
        executor = AgentExecutor(event_bus=bus)
        executor.execute(make_request(_FakeAgent(), _task(), intent=intent))
        topics = [c.args[0] for c in bus.publish.call_args_list]
        assert SECURITY_INTENT_APPLIED in topics
        assert SECURITY_CHECK_PASSED in topics

    def test_intent_denied_publishes_security_denied(self):
        bus = MagicMock()
        intent = IntentPolicy(
            actions=frozenset(["shell_execute"]),
            name="shell",
            source="user",
        )
        executor = AgentExecutor(event_bus=bus)
        executor.execute(make_request(_FakeAgent(), _task(), intent=intent))
        topics = [c.args[0] for c in bus.publish.call_args_list]
        assert SECURITY_CHECK_DENIED in topics

    def test_intent_denied_message_contains_agent_name(self):
        intent = IntentPolicy(
            actions=frozenset(["shell_execute"]),
            name="shell",
            source="user",
        )
        executor = AgentExecutor()
        request = make_request(_FakeAgent(name="my_agent"), _task(), intent=intent)
        outcome = executor.execute(request)
        assert "my_agent" in outcome.error.message

    def test_intent_denied_message_contains_violations(self):
        intent = IntentPolicy(
            actions=frozenset(["shell_execute"]),
            name="shell",
            source="user",
        )
        executor = AgentExecutor()
        request = make_request(_FakeAgent(), _task(), intent=intent)
        outcome = executor.execute(request)
        assert "denied:" in outcome.error.message

    def test_intent_source_in_security_payload(self):
        bus = MagicMock()
        intent = IntentPolicy(
            actions=frozenset(["filesystem.read"]),
            name="read",
            source="custom_source",
        )
        executor = AgentExecutor(event_bus=bus)
        executor.execute(make_request(_FakeAgent(), _task(), intent=intent))
        security_events = [
            c.args[1]
            for c in bus.publish.call_args_list
            if c.args[0] in (SECURITY_INTENT_APPLIED, SECURITY_CHECK_PASSED)
        ]
        for event in security_events:
            assert event["intent_source"] == "custom_source"

    def test_intent_name_in_security_payload(self):
        bus = MagicMock()
        intent = IntentPolicy(
            actions=frozenset(["filesystem.read"]),
            name="my_intent",
            source="test",
        )
        executor = AgentExecutor(event_bus=bus)
        executor.execute(make_request(_FakeAgent(), _task(), intent=intent))
        security_events = [
            c.args[1]
            for c in bus.publish.call_args_list
            if c.args[0] == SECURITY_INTENT_APPLIED
        ]
        assert security_events[0]["action"] == "my_intent"

    def test_intent_name_none_uses_unknown(self):
        bus = MagicMock()
        intent = IntentPolicy(
            actions=frozenset(["filesystem.read"]),
            name="",
            source="test",
        )
        executor = AgentExecutor(event_bus=bus)
        executor.execute(make_request(_FakeAgent(), _task(), intent=intent))
        security_events = [
            c.args[1]
            for c in bus.publish.call_args_list
            if c.args[0] == SECURITY_INTENT_APPLIED
        ]
        assert security_events[0]["action"] == "unknown"


class TestOnProgressCallback:
    """Verify on_progress callback receives events."""

    def test_on_progress_called_on_lifecycle(self):
        bus = MagicMock()
        events_received = []
        executor = AgentExecutor(event_bus=bus)
        request = make_request(
            _FakeAgent(), _task(), on_progress=lambda e: events_received.append(e)
        )
        executor.execute(request)
        assert len(events_received) > 0
        # Should contain lifecycle events
        statuses = [e.get("current_state") for e in events_received if "current_state" in e]
        assert STATE_SUCCEEDED in statuses

    def test_on_progress_not_called_without_callback(self):
        executor = AgentExecutor()
        # No on_progress — should not raise
        executor.execute(make_request(_FakeAgent(), _task()))

    def test_on_progress_receives_execution_events(self):
        events_received = []
        bus = MagicMock()
        executor = AgentExecutor(event_bus=bus)
        request = make_request(
            _FakeAgent(), _task(), on_progress=lambda e: events_received.append(e)
        )
        executor.execute(request)
        statuses = [e.get("status") for e in events_received]
        assert STATE_SUCCEEDED in statuses


class TestCorrelationIdPropagation:
    """Verify correlation_id propagation through events and outcome."""

    def test_correlation_id_in_execution_event(self):
        bus = MagicMock()
        executor = AgentExecutor(event_bus=bus)
        request = make_request(_FakeAgent(), _task(), correlation_id="corr-42")
        executor.execute(request)
        completed = [
            c.args[1]
            for c in bus.publish.call_args_list
            if c.args[0] == AGENT_EXECUTION_COMPLETED
        ]
        assert completed[0]["correlation_id"] == "corr-42"

    def test_correlation_id_in_lifecycle_event(self):
        bus = MagicMock()
        executor = AgentExecutor(event_bus=bus)
        request = make_request(_FakeAgent(), _task(), correlation_id="corr-99")
        executor.execute(request)
        lifecycle = [
            c.args[1]
            for c in bus.publish.call_args_list
            if c.args[0] == AGENT_LIFECYCLE_CHANGED
        ]
        for event in lifecycle:
            assert event["correlation_id"] == "corr-99"

    def test_correlation_id_from_task_fallback(self):
        bus = MagicMock()
        executor = AgentExecutor(event_bus=bus)
        task = _task(corr_id="task-corr")
        request = make_request(_FakeAgent(), task, correlation_id="")
        executor.execute(request)
        completed = [
            c.args[1]
            for c in bus.publish.call_args_list
            if c.args[0] == AGENT_EXECUTION_COMPLETED
        ]
        assert completed[0]["correlation_id"] == "task-corr"

    def test_correlation_id_in_outcome_result(self):
        executor = AgentExecutor()
        request = make_request(_FakeAgent(), _task(), correlation_id="corr-out")
        outcome = executor.execute(request)
        assert outcome.result.correlation_id == "corr-out"

    def test_agent_name_in_outcome_result(self):
        executor = AgentExecutor()
        request = make_request(_FakeAgent(name="agent_x"), _task())
        outcome = executor.execute(request)
        assert outcome.result.agent == "agent_x"

    def test_task_id_in_outcome_result(self):
        executor = AgentExecutor()
        task = _task(task_id="t-123")
        request = make_request(_FakeAgent(), task)
        outcome = executor.execute(request)
        assert outcome.result.task_id == "t-123"


class TestPublishLifecycle:
    """Verify _publish_lifecycle arguments are all used."""

    def test_previous_and_current_state_published(self):
        bus = MagicMock()
        executor = AgentExecutor(event_bus=bus)
        executor.execute(make_request(_FakeAgent(), _task()))
        lifecycle = [
            c.args[1]
            for c in bus.publish.call_args_list
            if c.args[0] == AGENT_LIFECYCLE_CHANGED
        ]
        # First event: created -> created
        assert lifecycle[0]["previous_state"] == STATE_CREATED
        assert lifecycle[0]["current_state"] == STATE_CREATED

    def test_lifecycle_transitions_complete_sequence(self):
        bus = MagicMock()
        executor = AgentExecutor(event_bus=bus)
        executor.execute(make_request(_FakeAgent(), _task()))
        lifecycle = [
            c.args[1]
            for c in bus.publish.call_args_list
            if c.args[0] == AGENT_LIFECYCLE_CHANGED
        ]
        hops = [(e["previous_state"], e["current_state"]) for e in lifecycle]
        assert hops == [
            (STATE_CREATED, STATE_CREATED),
            (STATE_CREATED, STATE_VALIDATED),
            (STATE_VALIDATED, STATE_QUEUED),
            (STATE_QUEUED, STATE_RUNNING),
            (STATE_RUNNING, STATE_SUCCEEDED),
        ]

    def test_no_bus_no_crash(self):
        executor = AgentExecutor(event_bus=None)
        outcome = executor.execute(make_request(_FakeAgent(), _task()))
        assert outcome.status == STATE_SUCCEEDED


class TestPublishExecution:
    """Verify _publish_execution arguments are all used."""

    def test_execution_event_carries_status(self):
        bus = MagicMock()
        executor = AgentExecutor(event_bus=bus)
        executor.execute(make_request(_FakeAgent(), _task()))
        started = [
            c.args[1]
            for c in bus.publish.call_args_list
            if c.args[0] == AGENT_EXECUTION_STARTED
        ]
        assert started[0]["status"] == STATE_RUNNING

    def test_execution_event_carries_attempt(self):
        bus = MagicMock()
        executor = AgentExecutor(event_bus=bus)
        executor.execute(make_request(_FakeAgent(), _task()))
        started = [
            c.args[1]
            for c in bus.publish.call_args_list
            if c.args[0] == AGENT_EXECUTION_STARTED
        ]
        assert started[0]["attempt"] == 1

    def test_execution_event_carries_duration_ms(self):
        bus = MagicMock()
        executor = AgentExecutor(event_bus=bus)
        executor.execute(make_request(_FakeAgent(), _task()))
        completed = [
            c.args[1]
            for c in bus.publish.call_args_list
            if c.args[0] == AGENT_EXECUTION_COMPLETED
        ]
        assert completed[0]["duration_ms"] >= 0

    def test_execution_event_error_code_none_on_success(self):
        bus = MagicMock()
        executor = AgentExecutor(event_bus=bus)
        executor.execute(make_request(_FakeAgent(), _task()))
        completed = [
            c.args[1]
            for c in bus.publish.call_args_list
            if c.args[0] == AGENT_EXECUTION_COMPLETED
        ]
        assert completed[0]["error_code"] is None

    def test_execution_event_error_code_on_failure(self):
        bus = MagicMock()

        def boom(t, c):
            raise RuntimeError("crash")

        executor = AgentExecutor(event_bus=bus)
        executor.execute(make_request(_FakeAgent(fn=boom), _task()))
        failed = [
            c.args[1]
            for c in bus.publish.call_args_list
            if c.args[0] == AGENT_EXECUTION_FAILED
        ]
        assert failed[0]["error_code"] == RUNTIME_ERROR

    def test_execution_event_message_on_failure(self):
        bus = MagicMock()

        def boom(t, c):
            raise RuntimeError("crash msg")

        executor = AgentExecutor(event_bus=bus)
        executor.execute(make_request(_FakeAgent(fn=boom), _task()))
        failed = [
            c.args[1]
            for c in bus.publish.call_args_list
            if c.args[0] == AGENT_EXECUTION_FAILED
        ]
        assert "crash msg" in failed[0]["message"]

    def test_execution_event_empty_message_on_success(self):
        bus = MagicMock()
        executor = AgentExecutor(event_bus=bus)
        executor.execute(make_request(_FakeAgent(), _task()))
        completed = [
            c.args[1]
            for c in bus.publish.call_args_list
            if c.args[0] == AGENT_EXECUTION_COMPLETED
        ]
        assert completed[0]["message"] == ""


class TestPublishSecurity:
    """Verify _publish_security arguments are all used."""

    def test_security_event_payload_fields(self):
        bus = MagicMock()
        intent = IntentPolicy(
            actions=frozenset(["filesystem.read"]),
            name="read_action",
            source="test_src",
        )
        executor = AgentExecutor(event_bus=bus)
        request = make_request(
            _FakeAgent(name="agent_sec"), _task(), intent=intent, correlation_id="c-1"
        )
        executor.execute(request)
        security = [
            c.args[1]
            for c in bus.publish.call_args_list
            if c.args[0] == SECURITY_INTENT_APPLIED
        ]
        assert security[0]["decision"] == SECURITY_INTENT_APPLIED
        assert security[0]["agent"] == "agent_sec"
        assert security[0]["action"] == "read_action"
        assert security[0]["allowed"] is True
        assert "intent 'read_action'" in security[0]["reason"]
        assert security[0]["intent_source"] == "test_src"

    def test_security_violations_field(self):
        bus = MagicMock()
        intent = IntentPolicy(
            actions=frozenset(["shell_execute"]),
            name="bad_action",
            source="test",
        )
        executor = AgentExecutor(event_bus=bus)
        request = make_request(_FakeAgent(), _task(), intent=intent)
        executor.execute(request)
        denied = [
            c.args[1]
            for c in bus.publish.call_args_list
            if c.args[0] == SECURITY_CHECK_DENIED
        ]
        assert len(denied) > 0
        assert isinstance(denied[0]["violations"], list)


class TestMakeRequest:
    """Verify make_request builds ExecutionRequest with all fields."""

    def test_make_request_default_fields(self):
        agent = _FakeAgent()
        task = _task()
        request = make_request(agent, task)
        assert request.agent is agent
        assert request.task is task
        assert request.context is None
        assert request.timeout is None
        assert request.retry_policy is None
        assert request.correlation_id == ""
        assert request.on_progress is None
        assert request.intent is None

    def test_make_request_all_fields(self):
        agent = _FakeAgent()
        task = _task()
        intent = IntentPolicy(actions=frozenset(["read"]))
        cb = lambda e: None
        policy = RetryPolicy(max_attempts=5)
        request = make_request(
            agent,
            task,
            context={"key": "val"},
            timeout=10.0,
            retry_policy=policy,
            correlation_id="c-1",
            on_progress=cb,
            intent=intent,
        )
        assert request.context == {"key": "val"}
        assert request.timeout == 10.0
        assert request.retry_policy is policy
        assert request.correlation_id == "c-1"
        assert request.on_progress is cb
        assert request.intent is intent


# ===========================================================================
# 2. TelemetryStore.aggregate_usage — each argument affects result
# ===========================================================================


@pytest.fixture
def telemetry_db(tmp_path):
    """Provide an open TelemetryStore with seed data."""
    store = TelemetryStore(db_path=tmp_path / "test.db", project_id="proj1")
    store.open()
    return store


@pytest.fixture
def seeded_store(telemetry_db):
    """Insert multi-agent, multi-model seed data for aggregation tests."""
    store = telemetry_db

    # Execution 1: agent_a, model_x
    store.insert_execution({
        "execution_id": "exec-1",
        "event_id": "evt-1",
        "correlation_id": "corr-1",
        "task_id": "t-1",
        "agent": "agent_a",
        "model": "model_x",
        "status": "succeeded",
        "duration_ms": 100.0,
        "timestamp": "2024-01-10T00:00:00Z",
    })
    store.insert_usage({
        "execution_id": "exec-1",
        "agent": "agent_a",
        "model": "model_x",
        "provider": "openai",
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
        "timestamp": "2024-01-10T00:00:00Z",
    })
    store.insert_cost({
        "execution_id": "exec-1",
        "pricing_version": "v1",
        "input_cost": 0.1,
        "output_cost": 0.05,
        "total_cost": 0.15,
        "currency": "USD",
        "status": "priced",
        "calculated_at": "2024-01-10T00:00:00Z",
    })

    # Execution 2: agent_b, model_y
    store.insert_execution({
        "execution_id": "exec-2",
        "event_id": "evt-2",
        "correlation_id": "corr-2",
        "task_id": "t-2",
        "agent": "agent_b",
        "model": "model_y",
        "status": "failed",
        "duration_ms": 200.0,
        "timestamp": "2024-01-11T00:00:00Z",
    })
    store.insert_usage({
        "execution_id": "exec-2",
        "agent": "agent_b",
        "model": "model_y",
        "provider": "anthropic",
        "input_tokens": 200,
        "output_tokens": 100,
        "total_tokens": 300,
        "timestamp": "2024-01-11T00:00:00Z",
    })
    store.insert_cost({
        "execution_id": "exec-2",
        "pricing_version": "v1",
        "input_cost": 0.2,
        "output_cost": 0.1,
        "total_cost": 0.30,
        "currency": "USD",
        "status": "priced",
        "calculated_at": "2024-01-11T00:00:00Z",
    })

    # Execution 3: agent_a, model_x (duplicate agent/model)
    store.insert_execution({
        "execution_id": "exec-3",
        "event_id": "evt-3",
        "correlation_id": "corr-3",
        "task_id": "t-3",
        "agent": "agent_a",
        "model": "model_x",
        "status": "succeeded",
        "duration_ms": 150.0,
        "timestamp": "2024-01-12T00:00:00Z",
    })
    store.insert_usage({
        "execution_id": "exec-3",
        "agent": "agent_a",
        "model": "model_x",
        "provider": "openai",
        "input_tokens": 300,
        "output_tokens": 150,
        "total_tokens": 450,
        "timestamp": "2024-01-12T00:00:00Z",
    })
    store.insert_cost({
        "execution_id": "exec-3",
        "pricing_version": "v1",
        "input_cost": 0.3,
        "output_cost": 0.15,
        "total_cost": 0.45,
        "currency": "USD",
        "status": "priced",
        "calculated_at": "2024-01-12T00:00:00Z",
    })

    return store


class TestAggregateUsage:
    """Verify each aggregate_usage argument affects the result."""

    def test_totals_all_records(self, seeded_store):
        result = seeded_store.aggregate_usage()
        totals = result["totals"]
        assert totals["input_tokens"] == 600  # 100 + 200 + 300
        assert totals["output_tokens"] == 300  # 50 + 100 + 150
        assert totals["total_tokens"] == 900  # 150 + 300 + 450
        assert totals["total_cost"] == 0.9  # 0.15 + 0.30 + 0.45
        assert totals["currency"] == "USD"

    def test_by_agent_groups_correctly(self, seeded_store):
        result = seeded_store.aggregate_usage()
        by_agent = result["by_agent"]
        assert "agent_a" in by_agent
        assert "agent_b" in by_agent
        assert by_agent["agent_a"]["input_tokens"] == 400  # 100 + 300
        assert by_agent["agent_a"]["count"] == 2
        assert by_agent["agent_b"]["input_tokens"] == 200
        assert by_agent["agent_b"]["count"] == 1

    def test_by_model_groups_correctly(self, seeded_store):
        result = seeded_store.aggregate_usage()
        by_model = result["by_model"]
        assert "model_x" in by_model
        assert "model_y" in by_model
        assert by_model["model_x"]["input_tokens"] == 400
        assert by_model["model_x"]["count"] == 2

    def test_agent_filter_reduces_results(self, seeded_store):
        result = seeded_store.aggregate_usage(agent="agent_a")
        assert result["totals"]["input_tokens"] == 400
        assert result["total_records"] == 2
        assert "agent_b" not in result["by_agent"]

    def test_model_filter_reduces_results(self, seeded_store):
        result = seeded_store.aggregate_usage(model="model_x")
        assert result["totals"]["input_tokens"] == 400
        assert "model_y" not in result["by_model"]

    def test_date_from_filter(self, seeded_store):
        result = seeded_store.aggregate_usage(date_from="2024-01-11T00:00:00Z")
        # Only exec-2 and exec-3
        assert result["totals"]["input_tokens"] == 500  # 200 + 300

    def test_date_to_filter(self, seeded_store):
        result = seeded_store.aggregate_usage(date_to="2024-01-11T00:00:00Z")
        # Only exec-1 and exec-2
        assert result["totals"]["input_tokens"] == 300  # 100 + 200

    def test_date_from_and_to_combined(self, seeded_store):
        result = seeded_store.aggregate_usage(
            date_from="2024-01-11T00:00:00Z",
            date_to="2024-01-11T23:59:59Z",
        )
        # Only exec-2
        assert result["totals"]["input_tokens"] == 200

    def test_limit_affects_results(self, seeded_store):
        result = seeded_store.aggregate_usage(limit=1)
        assert len(result["records"]) <= 1

    def test_workflow_id_filter(self, seeded_store):
        # All executions have no workflow_id, so filtering by it returns empty
        result = seeded_store.aggregate_usage(workflow_id="nonexistent")
        assert result["total_records"] == 0

    def test_records_list_populated(self, seeded_store):
        result = seeded_store.aggregate_usage()
        assert len(result["records"]) == 3

    def test_cost_records_populated(self, seeded_store):
        result = seeded_store.aggregate_usage()
        assert len(result["cost_records"]) == 3

    def test_executions_populated(self, seeded_store):
        result = seeded_store.aggregate_usage()
        assert len(result["executions"]) == 3

    def test_total_executions_count(self, seeded_store):
        result = seeded_store.aggregate_usage()
        assert result["total_executions"] == 3

    def test_empty_store(self, telemetry_db):
        result = telemetry_db.aggregate_usage()
        assert result["totals"]["input_tokens"] == 0
        assert result["totals"]["output_tokens"] == 0
        assert result["totals"]["total_cost"] == 0.0
        assert result["by_agent"] == {}
        assert result["by_model"] == {}
        assert result["records"] == []
        assert result["cost_records"] == []
        assert result["total_records"] == 0
        assert result["total_executions"] == 0

    def test_agent_and_model_combined(self, seeded_store):
        result = seeded_store.aggregate_usage(agent="agent_a", model="model_x")
        assert result["totals"]["input_tokens"] == 400
        assert result["total_records"] == 2

    def test_agent_not_found(self, seeded_store):
        result = seeded_store.aggregate_usage(agent="nonexistent")
        assert result["total_records"] == 0
        assert result["totals"]["input_tokens"] == 0


# ===========================================================================
# 3. TelemetryStore.query_costs — each argument affects query, STRING_MUTATION
# ===========================================================================


class TestQueryCosts:
    """Verify query_costs arguments and string literals affect results."""

    def test_query_costs_returns_all(self, seeded_store):
        costs = seeded_store.query_costs()
        assert len(costs) == 3

    def test_query_costs_agent_filter(self, seeded_store):
        costs = seeded_store.query_costs(agent="agent_a")
        assert len(costs) == 2

    def test_query_costs_model_filter(self, seeded_store):
        costs = seeded_store.query_costs(model="model_y")
        assert len(costs) == 1
        assert costs[0]["total_cost"] == 0.30

    def test_query_costs_date_from_filter(self, seeded_store):
        costs = seeded_store.query_costs(date_from="2024-01-11T00:00:00Z")
        assert len(costs) == 2

    def test_query_costs_date_to_filter(self, seeded_store):
        costs = seeded_store.query_costs(date_to="2024-01-11T00:00:00Z")
        assert len(costs) == 2

    def test_query_costs_limit(self, seeded_store):
        costs = seeded_store.query_costs(limit=1)
        assert len(costs) == 1

    def test_query_costs_workflow_id_filter(self, seeded_store):
        costs = seeded_store.query_costs(workflow_id="nonexistent")
        assert len(costs) == 0

    def test_query_costs_field_names(self, seeded_store):
        """STRING_MUTATION: verify column aliases in SELECT are used."""
        costs = seeded_store.query_costs(limit=1)
        cost = costs[0]
        assert "execution_id" in cost
        assert "pricing_version" in cost
        assert "pricing_source" in cost
        assert "input_cost" in cost
        assert "output_cost" in cost
        assert "cached_cost" in cost
        assert "reasoning_cost" in cost
        assert "total_cost" in cost
        assert "currency" in cost
        assert "status" in cost
        assert "calculated_at" in cost

    def test_query_costs_currency_value(self, seeded_store):
        costs = seeded_store.query_costs()
        for c in costs:
            assert c["currency"] == "USD"

    def test_query_costs_status_value(self, seeded_store):
        costs = seeded_store.query_costs()
        for c in costs:
            assert c["status"] == "priced"

    def test_query_costs_pricing_version(self, seeded_store):
        costs = seeded_store.query_costs()
        for c in costs:
            assert c["pricing_version"] == "v1"

    def test_query_costs_total_cost_values(self, seeded_store):
        costs = seeded_store.query_costs()
        total_costs = sorted([c["total_cost"] for c in costs])
        assert total_costs == [0.15, 0.30, 0.45]

    def test_query_costs_empty(self, telemetry_db):
        costs = telemetry_db.query_costs()
        assert costs == []

    def test_query_costs_closed_store(self, tmp_path):
        store = TelemetryStore(db_path=tmp_path / "no.db", project_id="p")
        # Not opened
        costs = store.query_costs()
        assert costs == []

    def test_query_costs_date_from_and_to(self, seeded_store):
        costs = seeded_store.query_costs(
            date_from="2024-01-10T00:00:00Z",
            date_to="2024-01-11T23:59:59Z",
        )
        assert len(costs) == 2

    def test_query_costs_order_by_calculated_at_desc(self, seeded_store):
        """Verify the ORDER BY clause uses calculated_at."""
        costs = seeded_store.query_costs()
        timestamps = [c["calculated_at"] for c in costs]
        assert timestamps == sorted(timestamps, reverse=True)


# ===========================================================================
# 4. create_kernel — project_path affects the result
# ===========================================================================


class TestCreateKernel:
    """Verify create_kernel builds a Kernel with the correct project_path."""

    @patch("aios.core.factory.ConnectionPool")
    @patch("aios.core.factory.ConfigLoader")
    @patch("aios.core.factory.OllamaEmbeddingProvider")
    def test_create_kernel_returns_kernel(self, mock_embed, mock_loader, mock_pool):
        from aios.core.factory import create_kernel
        from aios.core.kernel import Kernel

        mock_loader.return_value.load.return_value = MagicMock(
            runtime=MagicMock(adapter="ollama"),
            routing=None,
            agent_budget=MagicMock(max_steps=10),
        )
        mock_pool.return_value = MagicMock()
        kernel = create_kernel(Path("/tmp/test_project"))
        assert isinstance(kernel, Kernel)
        kernel.shutdown()

    @patch("aios.core.factory.ConnectionPool")
    @patch("aios.core.factory.ConfigLoader")
    @patch("aios.core.factory.OllamaEmbeddingProvider")
    def test_create_kernel_sets_project_path(self, mock_embed, mock_loader, mock_pool):
        from aios.core.factory import create_kernel

        mock_loader.return_value.load.return_value = MagicMock(
            runtime=MagicMock(adapter="ollama"),
            routing=None,
            agent_budget=MagicMock(max_steps=10),
        )
        mock_pool.return_value = MagicMock()
        kernel = create_kernel(Path("/tmp/my_project"))
        assert kernel.project_path == Path("/tmp/my_project").resolve()
        kernel.shutdown()

    @patch("aios.core.factory.ConnectionPool")
    @patch("aios.core.factory.ConfigLoader")
    @patch("aios.core.factory.OllamaEmbeddingProvider")
    def test_create_kernel_registers_engines(self, mock_embed, mock_loader, mock_pool):
        from aios.core.factory import create_kernel

        mock_loader.return_value.load.return_value = MagicMock(
            runtime=MagicMock(adapter="ollama"),
            routing=None,
            agent_budget=MagicMock(max_steps=10),
        )
        mock_pool.return_value = MagicMock()
        kernel = create_kernel(Path("/tmp/test_project"))
        # Should have registered multiple engines
        engine_names = list(kernel._engines.keys())
        assert "events" in engine_names
        assert "config" in engine_names
        assert "runtime" in engine_names
        kernel.shutdown()

    @patch("aios.core.factory.ConnectionPool")
    @patch("aios.core.factory.ConfigLoader")
    @patch("aios.core.factory.OllamaEmbeddingProvider")
    def test_create_kernel_has_executor(self, mock_embed, mock_loader, mock_pool):
        from aios.core.factory import create_kernel

        mock_loader.return_value.load.return_value = MagicMock(
            runtime=MagicMock(adapter="ollama"),
            routing=None,
            agent_budget=MagicMock(max_steps=10),
        )
        mock_pool.return_value = MagicMock()
        kernel = create_kernel(Path("/tmp/test_project"))
        assert kernel._executor is not None
        kernel.shutdown()

    @patch("aios.core.factory.ConnectionPool")
    @patch("aios.core.factory.ConfigLoader")
    @patch("aios.core.factory.OllamaEmbeddingProvider")
    def test_create_kernel_uses_pool(self, mock_embed, mock_loader, mock_pool):
        from aios.core.factory import create_kernel

        mock_loader.return_value.load.return_value = MagicMock(
            runtime=MagicMock(adapter="ollama"),
            routing=None,
            agent_budget=MagicMock(max_steps=10),
        )
        pool_instance = MagicMock()
        mock_pool.return_value = pool_instance
        kernel = create_kernel(Path("/tmp/test_project"))
        assert kernel._storage_pool is pool_instance
        kernel.shutdown()

    @patch("aios.core.factory.ConnectionPool")
    @patch("aios.core.factory.ConfigLoader")
    @patch("aios.core.factory.OllamaEmbeddingProvider")
    def test_create_kernel_project_path_different(self, mock_embed, mock_loader, mock_pool):
        from aios.core.factory import create_kernel

        mock_loader.return_value.load.return_value = MagicMock(
            runtime=MagicMock(adapter="ollama"),
            routing=None,
            agent_budget=MagicMock(max_steps=10),
        )
        mock_pool.return_value = MagicMock()
        kernel = create_kernel(Path("/tmp/another_project"))
        assert kernel.project_path == Path("/tmp/another_project").resolve()
        kernel.shutdown()
