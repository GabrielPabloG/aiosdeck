"""PlannerAgent — decomposes goals into ordered subtasks.

Read-only agent. Receives a high-level goal, builds a planning prompt
with project context, delegates to AgentExecutor, and parses the LLM
output as a structured JSON plan.
"""

import json
import logging

from aios.agents.base import BaseAgent
from aios.agents.executor import AgentExecutor
from aios.agents.models import AgentResult, ExecutionRequest
from aios.core.task import Task
from aios.prompts import PromptBuilder

logger = logging.getLogger("aios.agent.planner")


class PlannerAgent(BaseAgent):
    name = "planner"
    required_capabilities = ["filesystem_read"]
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
        prompt = self._build_planning_prompt(task, context)
        request = ExecutionRequest(
            invoke=lambda: self._runtime.execute(
                prompt, self.required_skills, self.required_capabilities
            ),
            timeout=120.0,
        )
        outcome = self._executor.execute(request)

        if outcome.error:
            logger.error("PlannerAgent execution failed: %s", outcome.error)
            return AgentResult(
                success=False,
                errors=[str(outcome.error)],
                duration_ms=outcome.duration_ms,
            )

        return self._parse_plan(outcome.output, outcome.duration_ms)

    def _build_planning_prompt(self, task: Task, context) -> str:
        plan_prompt = (
            "## Role: Task Planner\n\n"
            "You are a software architecture planner. "
            "Given a high-level goal and project context, "
            "decompose it into ordered subtasks with dependencies.\n\n"
            f"Goal: {task.description}\n\n"
            "Output a JSON object with these fields:\n"
            '- "goal": the original goal\n'
            '- "subtasks": array of objects with:\n'
            "    id (string), type (code|test|documentation),\n"
            "    description (string),\n"
            "    priority (high|medium|low),\n"
            "    dependencies (array of task ids),\n"
            "    estimated_complexity (low|medium|high)\n"
            '- "risks": array of strings\n'
            '- "unknowns": array of strings\n\n'
            "Return ONLY the JSON object. No markdown, no explanation.\n\n"
            "---\n\n"
            "## Project Context\n\n"
        )
        base_prompt = self._builder.build(task, context)
        return plan_prompt + base_prompt

    def _parse_plan(self, output: str, duration_ms: float) -> AgentResult:
        json_str = self._extract_json(output)
        if not json_str:
            return AgentResult(
                success=False,
                errors=["Model output contains no JSON object"],
                duration_ms=duration_ms,
            )

        try:
            plan = json.loads(json_str)
        except json.JSONDecodeError as exc:
            return AgentResult(
                success=False,
                errors=[f"Model returned invalid JSON: {exc}"],
                duration_ms=duration_ms,
            )

        if not isinstance(plan, dict) or "subtasks" not in plan:
            return AgentResult(
                success=False,
                errors=['Model output missing required field: "subtasks"'],
                duration_ms=duration_ms,
            )

        return AgentResult(
            success=True,
            output=json.dumps(plan, indent=2),
            duration_ms=duration_ms,
        )

    @staticmethod
    def _extract_json(text: str) -> str:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or start >= end:
            return ""
        return text[start : end + 1]
