"""AgentExecutor — the single execution boundary for every agent.

AgentExecutor is the only component that may:

- validate an AgentTask (VALIDATION_ERROR),
- enforce agent capabilities (PERMISSION_DENIED),
- manage the agent lifecycle
  (created → validated → queued → running → succeeded|failed|timed_out|cancelled),
- apply timeout, retry, and cancellation centrally,
- publish the two-tier lifecycle/execution events:
    ``agent.lifecycle.changed`` for every state transition (including the
    ``created -> created`` initialization event), and
    ``agent.execution.{started,progress,completed,failed,timed_out,retried,cancelled}``
    for execution observability.

It invokes ``request.agent.execute(request.task, request.context)`` — the
agent's contract method — and never recurses: agents are executor-free and
expose ``execute()`` as their only public execution entry point.

The Executor does not know about prompts, LLMs, or runtimes. It only
orchestrates the execution of an Agent.
"""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError

from aios.agents.contracts import (
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
    AgentError,
    AgentExecutionEvent,
    AgentLifecycleEvent,
    error_from_exception,
    validate_agent_task,
)
from aios.agents.lifecycle import AgentLifecycle
from aios.agents.models import ExecutionOutcome, ExecutionRequest
from aios.events.events import (
    AGENT_EXECUTION_CANCELLED,
    AGENT_EXECUTION_COMPLETED,
    AGENT_EXECUTION_FAILED,
    AGENT_EXECUTION_RETRIED,
    AGENT_EXECUTION_STARTED,
    AGENT_EXECUTION_TIMED_OUT,
    AGENT_LIFECYCLE_CHANGED,
)


def make_request(  # noqa: PLR0913 - the request is the full run contract
    agent,
    task,
    context=None,
    *,
    timeout=None,
    retry_policy=None,
    correlation_id="",
    on_progress=None,
) -> ExecutionRequest:
    """Build an ExecutionRequest for a single agent run."""
    return ExecutionRequest(
        agent=agent,
        task=task,
        context=context,
        timeout=timeout,
        retry_policy=retry_policy,
        correlation_id=correlation_id,
        on_progress=on_progress,
    )


class AgentExecutor:
    def __init__(self, event_bus=None, capabilities_enforcer=None) -> None:
        self._bus = event_bus
        self._enforcer = capabilities_enforcer
        self._cancelled = False
        self.executor_id = str(uuid.uuid4())

    def set_event_bus(self, event_bus) -> None:
        """Wire the event bus late (the Kernel builds it during startup)."""
        self._bus = event_bus

    def cancel(self) -> None:
        """Request cancellation. Best-effort: running work is not hard-killed."""
        self._cancelled = True

    def execute(self, request: ExecutionRequest) -> ExecutionOutcome:  # noqa: PLR0911, PLR0915
        self._cancelled = False
        self._sequence = 0
        lifecycle = AgentLifecycle()
        attempt = 1
        retried = False
        timeout = self._resolve_timeout(request)
        retry_policy = request.retry_policy or request.agent.metadata.retry_policy
        max_attempts = retry_policy.max_attempts if retry_policy else 1
        started = time.monotonic()

        # Initialization event — not a state transition. Guarantees every
        # execution emits a complete, deterministic sequence starting at 1.
        self._publish_lifecycle(request, STATE_CREATED, STATE_CREATED)

        # 1. Validate the task
        validation_errors = validate_agent_task(request.task)
        if validation_errors:
            error = AgentError(
                code=VALIDATION_ERROR,
                message="; ".join(validation_errors),
                transient=False,
            )
            lifecycle.transition(STATE_FAILED)
            self._publish_lifecycle(request, STATE_CREATED, STATE_FAILED)
            self._publish_execution(
                request, AGENT_EXECUTION_FAILED, STATE_FAILED, 0.0, attempt, error
            )
            return ExecutionOutcome(status=STATE_FAILED, error=error, attempts=attempt)

        # 2. Enforce capabilities
        if self._enforcer is not None:
            try:
                self._enforcer.validate(request.agent)
            except PermissionError as exc:
                error = AgentError(code=PERMISSION_DENIED, message=str(exc), transient=False)
                lifecycle.transition(STATE_FAILED)
                self._publish_lifecycle(request, STATE_CREATED, STATE_FAILED)
                self._publish_execution(
                    request, AGENT_EXECUTION_FAILED, STATE_FAILED, 0.0, attempt, error
                )
                return ExecutionOutcome(status=STATE_FAILED, error=error, attempts=attempt)

        # 3. validated
        lifecycle.transition(STATE_VALIDATED)
        self._publish_lifecycle(request, STATE_CREATED, STATE_VALIDATED)

        # 4. queued — accepted by the system, not yet consuming execution
        lifecycle.transition(STATE_QUEUED)
        self._publish_lifecycle(request, STATE_VALIDATED, STATE_QUEUED)

        # 5. running
        lifecycle.transition(STATE_RUNNING)
        self._publish_lifecycle(request, STATE_QUEUED, STATE_RUNNING)

        # 6. Attempt loop
        while True:
            if self._cancelled:
                lifecycle.transition(STATE_CANCELLED)
                self._publish_lifecycle(request, STATE_RUNNING, STATE_CANCELLED)
                self._publish_execution(
                    request,
                    AGENT_EXECUTION_CANCELLED,
                    STATE_CANCELLED,
                    self._elapsed(started),
                    attempt,
                )
                return ExecutionOutcome(
                    status=STATE_CANCELLED, duration_ms=self._elapsed(started), attempts=attempt
                )

            self._publish_execution(
                request, AGENT_EXECUTION_STARTED, STATE_RUNNING, self._elapsed(started), attempt
            )
            try:
                result = self._invoke(request, timeout)
                duration = self._elapsed(started)
                result.duration_ms = duration
                result.agent = request.agent.name
                result.task_id = request.task.task_id
                result.correlation_id = request.correlation_id or request.task.correlation_id
                if result.success:
                    lifecycle.transition(STATE_SUCCEEDED)
                    self._publish_lifecycle(request, STATE_RUNNING, STATE_SUCCEEDED)
                    self._publish_execution(
                        request, AGENT_EXECUTION_COMPLETED, STATE_SUCCEEDED, duration, attempt
                    )
                    return ExecutionOutcome(
                        status=STATE_SUCCEEDED,
                        result=result,
                        duration_ms=duration,
                        attempts=attempt,
                        retried=retried,
                    )
                error = result.error or AgentError(
                    code=result.error_code or RUNTIME_ERROR,
                    message="; ".join(result.errors) or "Agent failed",
                    transient=False,
                )
                lifecycle.transition(STATE_FAILED)
                self._publish_lifecycle(request, STATE_RUNNING, STATE_FAILED)
                self._publish_execution(
                    request, AGENT_EXECUTION_FAILED, STATE_FAILED, duration, attempt, error
                )
                return ExecutionOutcome(
                    status=STATE_FAILED,
                    result=result,
                    error=error,
                    duration_ms=duration,
                    attempts=attempt,
                    retried=retried,
                )
            except TimeoutError:
                error = AgentError(
                    code=TIMEOUT,
                    message=f"Execution timed out after {timeout}s",
                    transient=True,
                )
                duration = self._elapsed(started)
                if self._should_retry(error, retry_policy, attempt, max_attempts):
                    retried = True
                    self._publish_execution(
                        request, AGENT_EXECUTION_RETRIED, STATE_RUNNING, duration, attempt, error
                    )
                    attempt += 1
                    lifecycle.transition(STATE_RUNNING)
                    self._publish_lifecycle(request, STATE_RUNNING, STATE_RUNNING)
                    time.sleep(self._backoff(retry_policy, attempt))
                    continue
                lifecycle.transition(STATE_TIMED_OUT)
                self._publish_lifecycle(request, STATE_RUNNING, STATE_TIMED_OUT)
                self._publish_execution(
                    request, AGENT_EXECUTION_TIMED_OUT, STATE_TIMED_OUT, duration, attempt, error
                )
                return ExecutionOutcome(
                    status=STATE_TIMED_OUT,
                    error=error,
                    duration_ms=duration,
                    attempts=attempt,
                    retried=retried,
                )
            except Exception as exc:  # noqa: BLE001 - executor maps every failure
                error = error_from_exception(exc)
                duration = self._elapsed(started)
                if self._should_retry(error, retry_policy, attempt, max_attempts):
                    retried = True
                    self._publish_execution(
                        request, AGENT_EXECUTION_RETRIED, STATE_RUNNING, duration, attempt, error
                    )
                    attempt += 1
                    lifecycle.transition(STATE_RUNNING)
                    self._publish_lifecycle(request, STATE_RUNNING, STATE_RUNNING)
                    time.sleep(self._backoff(retry_policy, attempt))
                    continue
                lifecycle.transition(STATE_FAILED)
                self._publish_lifecycle(request, STATE_RUNNING, STATE_FAILED)
                self._publish_execution(
                    request, AGENT_EXECUTION_FAILED, STATE_FAILED, duration, attempt, error
                )
                return ExecutionOutcome(
                    status=STATE_FAILED,
                    error=error,
                    duration_ms=duration,
                    attempts=attempt,
                    retried=retried,
                )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _invoke(self, request: ExecutionRequest, timeout: float | None):
        if timeout is None:
            return request.agent.execute(request.task, request.context)
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(request.agent.execute, request.task, request.context)
            return future.result(timeout=timeout)
        except TimeoutError:
            future.cancel()
            raise
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _resolve_timeout(request: ExecutionRequest) -> float | None:
        metadata = request.agent.metadata
        if request.timeout is not None and metadata.allow_timeout_override:
            return request.timeout
        return metadata.timeout

    @staticmethod
    def _should_retry(error: AgentError, policy, attempt: int, max_attempts: int) -> bool:
        if policy is None or attempt >= max_attempts:
            return False
        return error.retryable and error.code in policy.retryable_codes

    @staticmethod
    def _backoff(policy, attempt: int) -> float:
        delay = policy.base_delay if policy else 0.5
        return delay * (2 ** (attempt - 2))

    @staticmethod
    def _elapsed(started: float) -> float:
        return (time.monotonic() - started) * 1000

    def _event_identity(self, request: ExecutionRequest) -> dict:
        return {
            "event_id": str(uuid.uuid4()),
            "agent": request.agent.name,
            "task_id": request.task.task_id,
            "correlation_id": request.correlation_id or request.task.correlation_id,
            "executor_id": self.executor_id,
            "sequence": self._sequence,
        }

    def _publish_lifecycle(
        self,
        request: ExecutionRequest,
        previous_state: str,
        current_state: str,
    ) -> None:
        if self._bus is None:
            return
        self._sequence += 1
        identity = self._event_identity(request)
        event = AgentLifecycleEvent(
            **identity,
            status=current_state,
            previous_state=previous_state,
            current_state=current_state,
        )
        self._bus.publish(
            AGENT_LIFECYCLE_CHANGED,
            event.to_dict(),
            correlation_id=identity["correlation_id"],
        )
        if request.on_progress is not None:
            request.on_progress(event.to_dict())

    def _publish_execution(  # noqa: PLR0913, PLR0917 - payload fields are the event contract
        self,
        request: ExecutionRequest,
        topic: str,
        status: str,
        duration_ms: float | None,
        attempt: int,
        error: AgentError | None = None,
    ) -> None:
        if self._bus is None:
            return
        self._sequence += 1
        identity = self._event_identity(request)
        event = AgentExecutionEvent(
            **identity,
            status=status,
            duration_ms=duration_ms,
            error_code=error.code if error else None,
            attempt=attempt,
            message=error.message if error else "",
        )
        self._bus.publish(topic, event.to_dict(), correlation_id=identity["correlation_id"])
        if request.on_progress is not None:
            request.on_progress(event.to_dict())
