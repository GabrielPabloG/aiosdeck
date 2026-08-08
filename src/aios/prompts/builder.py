"""PromptBuilder — task + context → final prompt string."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aios.agents import Task
    from aios.context.packet import ContextPacket
    from aios.skills.retrieval import SkillContext


class PromptBuilder:
    def build(
        self,
        task: Task,
        context: ContextPacket,
        skill_contexts: list[SkillContext] | None = None,
    ) -> str:
        sections = [
            self._task_section(task),
            self._context_section(context),
            self._git_section(context),
            self._research_section(context),
            self._memory_section(context),
        ]
        if skill_contexts:
            sections.append(self._smart_skills_section(skill_contexts))
        else:
            sections.append(self._skills_section(context))
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

    def _research_section(self, context: ContextPacket) -> str:
        research = getattr(context, "research", None)
        if not research:
            return ""
        summary = research.get("summary_short", "")
        if not summary:
            return ""
        return f"## Research\n{summary}"

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

    @staticmethod
    def _smart_skills_section(skill_contexts: list[SkillContext]) -> str:
        lines = ["## Relevant Skills"]
        for sc in skill_contexts:
            scored = sc.skill
            skill = scored.skill
            trigger_info = (
                f" [triggers: {', '.join(scored.trigger_matches)}]"
                if scored.trigger_matches
                else ""
            )
            scope_info = (
                f" [scope: {', '.join(scored.scope_matches)}]" if scored.scope_matches else ""
            )
            lines.append(f"- **{skill.name}** (score={scored.score:.2f}){trigger_info}{scope_info}")
            if skill.description:
                lines.append(f"  {skill.description}")

        lines.append("")
        for sc in skill_contexts:
            for chunk in sc.chunks:
                lines.append(chunk.result.content)

        lines.append("")
        lines.append("[Audit]")
        selected_names = ", ".join(
            f"{c.skill.skill.name} ({c.relevance_score:.2f})" for c in skill_contexts
        )
        lines.append(f"- selected: {selected_names}")
        tokens_total = sum(c.tokens_used for c in skill_contexts)
        lines.append(f"- tokens used: {tokens_total}")
        lines.append(f"- budget: {tokens_total} tokens")

        return "\n".join(lines)
