"""AgentExecutor — generic execution guardrail for agents.

The Executor does not know about agents, prompts, LLMs, or runtimes.
It receives an ExecutionRequest with a callable and returns an
ExecutionOutcome. Timeout, retry, and event bus integration are
handled here — once, for all agents.
"""

import time

from aios.agents.models import ExecutionOutcome, ExecutionRequest
from aios.events.events import (
    AGENT_EXECUTION_FAILED,
    AGENT_EXECUTION_FINISHED,
    AGENT_EXECUTION_STARTED,
)


class AgentExecutor:
    def __init__(self, event_bus=None) -> None:
        self._bus = event_bus

    def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
        self._publish(AGENT_EXECUTION_STARTED, request)
        start = time.monotonic()

        try:
            output = request.invoke()
            duration = (time.monotonic() - start) * 1000
            outcome = ExecutionOutcome(output=output, duration_ms=duration)
            self._publish(AGENT_EXECUTION_FINISHED, outcome)
            return outcome
        except Exception as exc:
            duration = (time.monotonic() - start) * 1000
            outcome = ExecutionOutcome(output="", duration_ms=duration, error=exc)
            self._publish(AGENT_EXECUTION_FAILED, outcome)
            return outcome

    def _publish(self, topic: str, payload: object) -> None:
        if self._bus is not None:
            self._bus.publish(topic, payload)
