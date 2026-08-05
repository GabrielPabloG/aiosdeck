"""ReviewerAgent — read-only specialist that evaluates code and returns a JSON verdict.

Does NOT interact with the user and does NOT write code. It reads the task and
project context, delegates evaluation to AgentExecutor, and parses the LLM
output as a strict JSON verdict: {"status": "pass"|"fail", "feedback": "..."}.
"""

import json
import logging

from aios.agents.base import BaseAgent
from aios.agents.executor import AgentExecutor
from aios.agents.models import AgentResult, ExecutionRequest
from aios.core.task import Task
from aios.prompts import PromptBuilder

logger = logging.getLogger("aios.agent.reviewer")

_VALID_STATUSES = ("pass", "fail")


class ReviewerAgent(BaseAgent):
    name = "reviewer"
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
        request = ExecutionRequest(
            invoke=lambda: self._runtime.execute(
                self._build_review_prompt(task, context),
                self.required_skills,
                self.required_capabilities,
            ),
            timeout=120.0,
        )
        outcome = self._executor.execute(request)

        if outcome.error:
            logger.error("ReviewerAgent execution failed: %s", outcome.error)
            return AgentResult(
                success=False,
                errors=[str(outcome.error)],
                duration_ms=outcome.duration_ms,
            )
        return self._parse_verdict(outcome.output, outcome.duration_ms)

    def _build_review_prompt(self, task: Task, context) -> str:
        review_prompt = (
            "## Role: Architecture Reviewer\n\n"
            "You are a rigorous architecture and code quality evaluator. "
            "You NEVER write code and you NEVER ask the user anything. "
            "Read the task and project context carefully and evaluate the code.\n\n"
            f"Task to review: {task.description}\n\n"
            "Output EXCLUSIVELY a JSON object with this format:\n"
            '- "status": "pass" or "fail"\n'
            '- "feedback": a concise string explaining the verdict\n\n'
            "Return ONLY the JSON object. No markdown, no explanation.\n\n"
            "---\n\n"
            "## Project Context\n\n"
        )
        base_prompt = self._builder.build(task, context)
        return review_prompt + base_prompt

    def _parse_verdict(self, output: str, duration_ms: float) -> AgentResult:
        json_str = self._extract_json(output)
        if not json_str:
            return AgentResult(
                success=False,
                errors=["Model output contains no JSON object"],
                duration_ms=duration_ms,
            )

        try:
            verdict = json.loads(json_str)
        except json.JSONDecodeError as exc:
            return AgentResult(
                success=False,
                errors=[f"Model returned invalid JSON: {exc}"],
                duration_ms=duration_ms,
            )

        if not isinstance(verdict, dict) or "status" not in verdict or "feedback" not in verdict:
            return AgentResult(
                success=False,
                errors=['Model output missing required fields: "status" and "feedback"'],
                duration_ms=duration_ms,
            )

        if verdict["status"] not in _VALID_STATUSES:
            return AgentResult(
                success=False,
                errors=[f'Model returned invalid status: "{verdict["status"]}"'],
                duration_ms=duration_ms,
            )

        return AgentResult(
            success=True,
            output=json.dumps(verdict, indent=2),
            duration_ms=duration_ms,
        )

    @staticmethod
    def _extract_json(text: str) -> str:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or start >= end:
            return ""
        return text[start : end + 1]
