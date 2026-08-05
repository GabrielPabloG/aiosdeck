"""PlannerAgent — decomposes goals into ordered subtasks.

Read-only agent. Receives a high-level goal, builds a planning prompt
with project context, delegates to AgentExecutor, and parses the LLM
output as a structured JSON plan.

The execution is a reasoning loop (max 3 iterations) with self-healing:
- If the LLM requests the `ask_user` tool, the tool is executed and its
  result is appended to the conversation history before retrying.
- If the LLM output is not valid JSON, the parse error is appended to
  the history and the LLM is asked to retry.
"""

import json
import logging
import re

from aios.agents.base import BaseAgent
from aios.agents.executor import AgentExecutor
from aios.agents.models import AgentResult, ExecutionRequest
from aios.core.task import Task
from aios.prompts import PromptBuilder
from aios.tools import ask_user

logger = logging.getLogger("aios.agent.planner")


_TOOL_CALL_RE = re.compile(r"ask_user\(\s*(['\"])(.*?)\1\s*\)")


class PlannerAgent(BaseAgent):
    name = "planner"
    required_capabilities = ["filesystem_read", "ask_user"]
    required_skills = ["project-dna", "coding-style"]
    max_iterations = 3

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
        transcript = [self._build_planning_prompt(task, context)]
        last_error = "Model failed to produce a valid plan"
        outcome = None

        for _ in range(self.max_iterations):
            outcome = self._invoke(self._build_transcript_prompt(transcript))

            if outcome.error:
                logger.error("PlannerAgent execution failed: %s", outcome.error)
                return AgentResult(
                    success=False,
                    errors=[str(outcome.error)],
                    duration_ms=outcome.duration_ms,
                )

            output = outcome.output

            tool_result = self._exec_tool_call(output)
            if tool_result is not None:
                transcript.append(f"[Assistant]: {output}")
                transcript.append(f"[Tool ask_user]: {tool_result}")
                continue

            result = self._parse_plan(output, outcome.duration_ms)
            if result.success:
                return result

            last_error = result.errors[0]
            transcript.append(f"[Assistant]: {output}")
            transcript.append(
                f"[System]: Error: Invalid format. {last_error} Please return strictly valid JSON."
            )

        duration_ms = outcome.duration_ms if outcome is not None else 0.0
        logger.error("PlannerAgent exceeded max iterations: %s", last_error)
        return AgentResult(
            success=False,
            errors=[f"Exceeded max iterations: {last_error}"],
            duration_ms=duration_ms,
        )

    def _invoke(self, prompt: str) -> ExecutionRequest:
        request = ExecutionRequest(
            invoke=lambda p=prompt: self._runtime.execute(
                p, self.required_skills, self.required_capabilities
            ),
            timeout=120.0,
        )
        return self._executor.execute(request)

    @staticmethod
    def _build_transcript_prompt(transcript: list[str]) -> str:
        return "\n\n".join(transcript)

    @staticmethod
    def _exec_tool_call(output: str) -> str | None:
        match = _TOOL_CALL_RE.search(output)
        if not match:
            return None
        return ask_user(match.group(2))

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
