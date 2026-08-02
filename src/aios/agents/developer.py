"""DeveloperAgent — minimal orchestrator. Context + Skills + Prompt + Runtime."""

import logging
from typing import TYPE_CHECKING

from aios.agents import AgentResult, Task
from aios.agents.base import BaseAgent

if TYPE_CHECKING:
    from aios.context.packet import ContextPacket

logger = logging.getLogger("aios.agent.developer")


class DeveloperAgent(BaseAgent):
    name = "developer"
    required_capabilities = ["filesystem_read", "filesystem_write", "shell"]
    required_skills = ["project-dna", "coding-style"]

    def __init__(self, runtime) -> None:
        self._runtime = runtime

    def execute(self, task: Task, context: "ContextPacket") -> AgentResult:
        skills = self.required_skills[:]
        if context.skills:
            skills.extend(context.skills)

        prompt = self._build_prompt(task, context, skills)

        try:
            output = self._runtime.execute(prompt, skills)
            return AgentResult(success=True, output=output)
        except Exception as exc:
            logger.error("DeveloperAgent execution failed: %s", exc)
            return AgentResult(success=False, output="", errors=[str(exc)])

    def _build_prompt(self, task: Task, context: "ContextPacket", skills: list[str]) -> str:
        parts = [f"## Task\n{task.description}"]

        parts.append("\n## Project Context")
        parts.append(f"- Language: {context.project.language}")
        parts.append(f"- Linter: {context.tools.linter or 'none'}")
        parts.append(f"- Formatter: {context.tools.formatter or 'none'}")
        parts.append(f"- Test runner: {context.tools.test_runner or 'none'}")

        parts.append("\n## Git Status")
        parts.append(f"- Branch: {context.git.branch or 'unknown'}")
        parts.append(f"- Status: {context.git.status}")

        if skills:
            parts.append("\n## Skills Loaded")
            for s in skills:
                parts.append(f"- {s}")

        return "\n".join(parts)
