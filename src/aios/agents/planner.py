"""PlannerAgent — decomposes goals into ordered subtasks.

Read-only agent. Receives a high-level goal, builds a planning prompt with
project context, and parses the LLM output as a structured JSON plan.

The execution is a reasoning loop (max 3 iterations) with self-healing:
- If the LLM requests the `ask_user` tool, the tool is executed and its
  result is appended to the conversation history before retrying.
- If the LLM output is not valid JSON, the parse error is appended to the
  history and the LLM is asked to retry.

This agent is executor-free: the AgentExecutor invokes ``execute()`` and
applies timeout/retry/events centrally. LLM/runtime exceptions propagate so
the executor can retry transient failures.
"""

import json
import logging
import re

from aios.agents.base import BaseAgent
from aios.agents.contracts import (
    RUNTIME_ERROR,
    STATE_FAILED,
    STATE_SUCCEEDED,
    TIMEOUT,
    AgentError,
    RetryPolicy,
    coerce_task,
)
from aios.agents.models import AgentResult
from aios.prompts import PromptBuilder
from aios.security.resolver import effective_permissions
from aios.tools import ask_user

logger = logging.getLogger("aios.agent.planner")

_TOOL_CALL_RE = re.compile(r"ask_user\(\s*(['\"])(.*?)\1\s*\)")


class PlannerAgent(BaseAgent):
    """Decomposes high-level goals into ordered subtasks.  Reads project
    structure and existing conventions to produce a structured plan of
    implementation steps."""
    name = "planner"
    timeout = 360.0
    retry_policy = RetryPolicy(
        max_attempts=2, base_delay=1.0, retryable_codes=(TIMEOUT, RUNTIME_ERROR)
    )
    required_capabilities = ["filesystem_read", "ask_user"]
    required_skills = ["project-dna", "coding-style"]
    max_iterations = 3

    def __init__(
        self, runtime, builder: PromptBuilder | None = None, skills=None, assembler=None
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
        transcript = [
            self._build_planning_prompt(
                agent_task, context, skill_contexts=skill_contexts, layered=layered
            )
        ]
        last_error = "Model failed to produce a valid plan"

        for _ in range(self.max_iterations):
            intent = getattr(context, "intent", None)
            effective = effective_permissions(intent, self.capabilities) if intent else None
            transcript_prompt = self._build_transcript_prompt(transcript)
            output = self._runtime.execute(
                transcript_prompt,
                self.required_skills,
                self.required_capabilities,
                permissions=effective,
                agent=self.name,
                task_type=agent_task.task_type,
                complexity=agent_task.params.get("complexity", "medium"),
                context_size=len(transcript_prompt.split()),
            )

            tool_result = self._exec_tool_call(output)
            if tool_result is not None:
                transcript.append(f"[Assistant]: {output}")
                transcript.append(f"[Tool ask_user]: {tool_result}")
                continue

            result = self._parse_plan(output)
            if result.success:
                result.agent = self.name
                result.task_id = agent_task.task_id
                result.correlation_id = agent_task.correlation_id
                result.status = STATE_SUCCEEDED
                return result

            last_error = result.errors[0]
            transcript.append(f"[Assistant]: {output}")
            transcript.append(
                f"[System]: Error: Invalid format. {last_error} Please return strictly valid JSON."
            )

        logger.error("PlannerAgent exceeded max iterations: %s", last_error)
        return AgentResult(
            success=False,
            errors=[f"Exceeded max iterations: {last_error}"],
            error=AgentError(code=RUNTIME_ERROR, message=f"Exceeded max iterations: {last_error}"),
            error_code=RUNTIME_ERROR,
            status=STATE_FAILED,
            agent=self.name,
            task_id=agent_task.task_id,
            correlation_id=agent_task.correlation_id,
        )

    @staticmethod
    def _build_transcript_prompt(transcript: list[str]) -> str:
        return "\n\n".join(transcript)

    @staticmethod
    def _exec_tool_call(output: str) -> str | None:
        match = _TOOL_CALL_RE.search(output)
        if not match:
            return None
        return ask_user(match.group(2))

    def _build_planning_prompt(self, task, context, skill_contexts=None, layered=None) -> str:
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
        base_prompt = self._builder.build(
            task, context, skill_contexts=skill_contexts, layered=layered
        )
        return plan_prompt + base_prompt

    def _parse_plan(self, output: str) -> AgentResult:
        json_str = self._extract_json(output)
        if not json_str:
            return AgentResult(
                success=False,
                errors=["Model output contains no JSON object"],
                error=AgentError(
                    code=RUNTIME_ERROR,
                    message="Model output contains no JSON object",
                ),
                error_code=RUNTIME_ERROR,
            )

        try:
            plan = json.loads(json_str)
        except json.JSONDecodeError as exc:
            return AgentResult(
                success=False,
                errors=[f"Model returned invalid JSON: {exc}"],
                error=AgentError(code=RUNTIME_ERROR, message=f"Model returned invalid JSON: {exc}"),
                error_code=RUNTIME_ERROR,
            )

        if not isinstance(plan, dict) or "subtasks" not in plan:
            return AgentResult(
                success=False,
                errors=['Model output missing required field: "subtasks"'],
                error=AgentError(
                    code=RUNTIME_ERROR,
                    message='Model output missing required field: "subtasks"',
                ),
                error_code=RUNTIME_ERROR,
            )

        return AgentResult(
            success=True,
            output=json.dumps(plan, indent=2),
        )

    @staticmethod
    def _extract_json(text: str) -> str:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or start >= end:
            return ""
        return text[start : end + 1]
