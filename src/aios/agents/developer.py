"""DeveloperAgent — prepares prompt, delegates execution to AgentExecutor."""

import logging

from aios.agents.base import BaseAgent
from aios.agents.executor import AgentExecutor
from aios.agents.models import AgentResult, ExecutionRequest
from aios.core.task import Task
from aios.prompts import PromptBuilder

logger = logging.getLogger("aios.agent.developer")


class DeveloperAgent(BaseAgent):
    name = "developer"
    required_capabilities = ["filesystem_read", "filesystem_write", "shell"]
    required_skills = ["project-dna", "coding-style"]

    def __init__(
        self,
        runtime,
        builder: PromptBuilder | None = None,
        executor: AgentExecutor | None = None,
    ) -> None:
        self._runtime = runtime
        self._builder = builder or PromptBuilder()
        self._executor = executor or AgentExecutor()

    def execute(self, task: Task, context) -> AgentResult:
        prompt = self._builder.build(task, context)
        request = ExecutionRequest(
            invoke=lambda: self._runtime.execute(prompt, self.required_skills),
        )
        outcome = self._executor.execute(request)

        if outcome.error:
            logger.error("DeveloperAgent execution failed: %s", outcome.error)
            return AgentResult(
                success=False,
                errors=[str(outcome.error)],
                duration_ms=outcome.duration_ms,
            )
        return AgentResult(
            success=True,
            output=outcome.output,
            duration_ms=outcome.duration_ms,
        )
