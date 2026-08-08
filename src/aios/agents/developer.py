"""DeveloperAgent — prepares a prompt and delegates execution to the runtime.

Executor-free by design: the AgentExecutor invokes ``execute()`` and applies
timeout/retry/events centrally. Runtime exceptions propagate so the executor
can retry transient failures.
"""

import logging

from aios.agents.base import BaseAgent
from aios.agents.contracts import STATE_SUCCEEDED, coerce_task
from aios.agents.models import AgentResult
from aios.prompts import PromptBuilder
from aios.security.resolver import effective_permissions

logger = logging.getLogger("aios.agent.developer")


class DeveloperAgent(BaseAgent):
    name = "developer"
    timeout = 600.0
    required_capabilities = ["filesystem_read", "filesystem_write", "shell"]
    required_skills = ["project-dna", "coding-style"]

    def __init__(
        self,
        runtime,
        builder: PromptBuilder | None = None,
        skills=None,
        assembler=None,
    ) -> None:
        super().__init__()
        self._runtime = runtime
        self._builder = builder or PromptBuilder()
        self._skills = skills
        self._assembler = assembler

    def execute(self, task, context) -> AgentResult:
        agent_task = coerce_task(task)
        skill_contexts = []
        if self._skills is not None:
            skill_contexts = self._skills.assemble(
                agent_task.description,
                context,
                agent=self.name,
                task_id=agent_task.task_id,
                correlation_id=agent_task.correlation_id,
            )
        layered = (
            self._assembler.assemble(agent_task, context, agent=self.name)
            if self._assembler is not None
            else None
        )
        prompt = self._builder.build(
            agent_task, context, skill_contexts=skill_contexts or None, layered=layered
        )
        intent = getattr(context, "intent", None)
        effective = effective_permissions(intent, self.capabilities) if intent else None
        output = self._runtime.execute(
            prompt, self.required_skills, self.required_capabilities, permissions=effective
        )
        return AgentResult(
            success=True,
            output=output,
            status=STATE_SUCCEEDED,
            agent=self.name,
            task_id=agent_task.task_id,
            correlation_id=agent_task.correlation_id,
        )
