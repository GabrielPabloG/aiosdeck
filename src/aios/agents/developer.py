"""DeveloperAgent — minimal orchestrator. Context + Skills + Prompt + Runtime."""

import logging

from aios.agents import AgentResult, Task
from aios.agents.base import BaseAgent
from aios.prompts import PromptBuilder

logger = logging.getLogger("aios.agent.developer")


class DeveloperAgent(BaseAgent):
    name = "developer"
    required_capabilities = ["filesystem_read", "filesystem_write", "shell"]
    required_skills = ["project-dna", "coding-style"]

    def __init__(self, runtime, builder: PromptBuilder | None = None) -> None:
        self._runtime = runtime
        self._builder = builder or PromptBuilder()

    def execute(self, task: Task, context) -> AgentResult:
        prompt = self._builder.build(task, context)

        try:
            output = self._runtime.execute(prompt, self.required_skills)
            return AgentResult(success=True, output=output)
        except Exception as exc:
            logger.error("DeveloperAgent execution failed: %s", exc)
            return AgentResult(success=False, output="", errors=[str(exc)])
