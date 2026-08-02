"""PromptBuilder — task + context → final prompt string."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aios.agents import Task
    from aios.context.packet import ContextPacket


class PromptBuilder:
    def build(self, task: Task, context: ContextPacket) -> str:
        sections = [
            self._task_section(task),
            self._context_section(context),
            self._git_section(context),
            self._memory_section(context),
            self._skills_section(context),
        ]
        return "\n\n".join(s for s in sections if s)

    def _task_section(self, task: Task) -> str:
        return f"## Task\n{task.description}"

    def _context_section(self, context: ContextPacket) -> str:
        parts = [
            "## Project Context",
            f"- Language: {context.project.language}",
            f"- Linter: {context.tools.linter or 'none'}",
            f"- Formatter: {context.tools.formatter or 'none'}",
            f"- Test runner: {context.tools.test_runner or 'none'}",
        ]
        return "\n".join(parts)

    def _git_section(self, context: ContextPacket) -> str:
        if not context.git.branch:
            return "## Git Status\n- Status: unknown"
        return f"## Git Status\n- Branch: {context.git.branch}\n- Status: {context.git.status}"

    def _memory_section(self, context: ContextPacket) -> str:
        if context.memory is None or context.memory.is_empty:
            return ""

        k = context.memory
        parts = ["## Memory"]
        if k.conventions:
            parts.append("Conventions:")
            for c in k.conventions:
                parts.append(f"- {c.rule}")
        if k.decisions:
            parts.append("Decisions:")
            for d in k.decisions:
                parts.append(f"- {d.title}")
        if k.patterns:
            parts.append("Patterns:")
            for p in k.patterns:
                parts.append(f"- {p.name}")
        if k.mistakes:
            parts.append("Mistakes to avoid:")
            for m in k.mistakes:
                parts.append(f"- {m.description}")
        return "\n".join(parts)

    def _skills_section(self, context: ContextPacket) -> str:
        if not context.skills:
            return ""
        parts = ["## Skills Loaded"]
        for s in context.skills:
            parts.append(f"- {s}")
        return "\n".join(parts)
