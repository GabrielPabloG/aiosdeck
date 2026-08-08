"""WorkflowEngine — linear orchestrator for the agent pipeline.

Runs Planner → Git(branch) → Scheduler → Developer → Reviewer → Tester →
Documentation → Git(commit) through public APIs only. The engine holds no
business logic: it calls agents and decides when to stop.
"""

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from aios.agents.contracts import AgentTask, coerce_task
from aios.agents.developer import DeveloperAgent
from aios.agents.documentation import DocumentationAgent
from aios.agents.executor import AgentExecutor, make_request
from aios.agents.git import GitAgent
from aios.agents.models import AgentResult
from aios.agents.planner import PlannerAgent
from aios.agents.research import ResearchAgent
from aios.agents.reviewer import ReviewerAgent
from aios.agents.tester import TesterAgent
from aios.config.schema import QualityConfig
from aios.core.task import Task
from aios.events.events import (
    QUALITY_COMPLETED,
    QUALITY_GATE_BLOCKED,
    QUALITY_GATE_COMPLETED,
    QUALITY_GATE_STARTED,
    QUALITY_STARTED,
)
from aios.quality.contracts import (
    GateInput,
    GateResult,
    GateStatus,
    QualityGate,
    Severity,
)
from aios.quality.gates import (
    CodeGate,
    DocumentationGate,
    ReleaseGate,
    SecurityGate,
    TestGate,
)
from aios.quality.policy import DecisionResult, resolve_decision
from aios.scheduler import KanbanEngine
from aios.security.actions import WORKFLOW_INTENT
from aios.workflow.models import (
    InMemoryRunIdGenerator,
    RunIdGenerator,
    WorkflowConfigurationError,
    WorkflowHealth,
    WorkflowResult,
    WorkflowStage,
    _WorkflowContext,
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")

logger = logging.getLogger("aios.workflow")

OPTIONAL_AGENTS = ("tester", "documentation", "git", "research")


def _findings_counts(result: GateResult) -> dict[str, int]:
    counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    for finding in result.findings:
        label = (
            finding.severity.value
            if isinstance(finding.severity, Severity)
            else str(finding.severity)
        )
        if label in counts:
            counts[label] += 1
    return counts


class WorkflowEngine:
    name = "workflow"

    def __init__(  # noqa: PLR0913 - the agents are the fixed pipeline contract
        self,
        *,
        planner: PlannerAgent,
        scheduler: KanbanEngine,
        developer: DeveloperAgent,
        reviewer: ReviewerAgent,
        executor: AgentExecutor,
        researcher: ResearchAgent | None = None,
        tester: TesterAgent | None = None,
        documentation: DocumentationAgent | None = None,
        git: GitAgent | None = None,
        project_path: Path | None = None,
        commit_factory: Callable[[_WorkflowContext], str] | None = None,
        run_ids: RunIdGenerator | None = None,
        quality_config: QualityConfig | None = None,
        quality_gates: dict[str, QualityGate] | None = None,
    ) -> None:
        agents = {
            "planner": planner,
            "scheduler": scheduler,
            "developer": developer,
            "reviewer": reviewer,
            "research": researcher,
            "tester": tester,
            "documentation": documentation,
            "git": git,
        }
        for name, agent in agents.items():
            if agent is None and name not in OPTIONAL_AGENTS:
                raise WorkflowConfigurationError(f"{name} agent is required")
        self._agents = agents
        self._optional_agents = list(OPTIONAL_AGENTS)
        self._project_path = project_path or Path.cwd()
        self._commit_factory = commit_factory or (lambda ctx: f"feat: {ctx.goal}")
        self._run_ids = run_ids or InMemoryRunIdGenerator()
        self._executor = executor
        self._quality_config = quality_config
        self._quality_gates = quality_gates
        self._bus = None

    def set_event_bus(self, bus) -> None:
        """Wire the event bus late (the Kernel builds it during startup)."""
        self._bus = bus

    def initialize(self) -> None:
        """No setup required."""

    def shutdown(self) -> None:
        """No cleanup required."""

    def health_check(self) -> WorkflowHealth:
        return WorkflowHealth(
            agents={name: agent is not None for name, agent in self._agents.items()},
            optional=self._optional_agents,
        )

    def execute(  # noqa: PLR0911, PLR0912, PLR0915 - linear pipeline with per-stage handling
        self,
        task: Task,
        context,
        on_stage: Callable[[WorkflowStage], None] | None = None,
    ) -> WorkflowResult:
        notify = on_stage or (lambda stage: None)
        ctx = _WorkflowContext(
            task=task,
            run_id=self._run_ids.next(),
            goal=task.description,
            started_at=datetime.now(UTC).isoformat(),
        )
        self._apply_workflow_intent(context)
        agents = self._agents
        gates = self._gates()
        ctx.quality_active = bool(gates)
        if gates:
            environment = self._quality_config.environment if self._quality_config else "dev"
            self._publish_quality(ctx, QUALITY_STARTED, {"environment": environment})

        # 0. Research — optional front-gate. Only runs when a researcher is
        # injected; its structured result feeds the planner/developer context.
        if agents["research"] is not None:
            self._run_research(ctx, task, context, notify)

        # 1. Planner
        plan_result = self._run_agent(agents["planner"], coerce_task(task), context)
        if not plan_result.success:
            ctx.stages.append(WorkflowStage(name="planner", success=False))
            notify(ctx.stages[-1])
            ctx.errors.append(plan_result.errors[0] if plan_result.errors else "Planner failed")
            return self._finish(ctx)
        ctx.plan = json.loads(plan_result.output)
        subtasks = ctx.plan.get("subtasks", [])
        ctx.subtask_count = len(subtasks)
        ctx.stages.append(WorkflowStage(name="planner", success=True, details={"plan": ctx.plan}))
        notify(ctx.stages[-1])

        # 2. Git — create the run branch before any scheduler persistence
        if agents["git"] is not None:
            branch = self._build_branch(ctx.run_id, ctx.goal)
            git_result = self._run_agent(
                agents["git"],
                AgentTask(
                    description=f"create branch {branch}",
                    task_type="create_branch",
                    params={"name": branch},
                ),
            )
            ctx.stages.append(
                WorkflowStage(
                    name="git",
                    success=git_result.success,
                    error=self._git_error(git_result),
                )
            )
            notify(ctx.stages[-1])
            if not git_result.success:
                ctx.errors.append(
                    f"Git: failed to create branch {branch}: {self._git_error(git_result)}"
                )
                return self._finish(ctx)
            ctx.branch = branch
        else:
            ctx.stages.append(WorkflowStage(name="git", success=True, details={"skipped": True}))
            notify(ctx.stages[-1])

        # 3. Scheduler
        board = agents["scheduler"].create_board(ctx.goal)
        ctx.board = board
        for subtask in subtasks:
            ctx.cards.append(agents["scheduler"].create_card(board.id, subtask["description"]))
        ctx.stages.append(WorkflowStage(name="scheduler", success=True))
        notify(ctx.stages[-1])

        # 4. Developer — one stage per subtask
        for i, subtask in enumerate(subtasks):
            card = ctx.cards[i]
            agents["scheduler"].begin_work(card.id)
            dev_task = AgentTask(
                description=subtask["description"], task_type=subtask.get("type", "code")
            )
            dev_result = self._run_agent(agents["developer"], dev_task, context)
            if not dev_result.success:
                agents["scheduler"].block_card(card.id, reason="execution failed")
                error = dev_result.errors[0] if dev_result.errors else "Developer failed"
                ctx.stages.append(
                    WorkflowStage(
                        name=f"developer:{i + 1}",
                        success=False,
                        error=error,
                        details={"description": subtask["description"]},
                    )
                )
                notify(ctx.stages[-1])
                ctx.errors.append(
                    f"Developer [{subtask['description']}]: "
                    f"{dev_result.errors[0] if dev_result.errors else 'failed'}"
                )
                return self._finish(ctx)
            agents["scheduler"].complete_work(card.id)
            ctx.completed_count += 1
            ctx.stages.append(
                WorkflowStage(
                    name=f"developer:{i + 1}",
                    success=True,
                    details={"description": subtask["description"]},
                )
            )
            notify(ctx.stages[-1])

        # 4b. Code gate — lint/format must pass before review
        if gates and not self._run_gate(
            ctx,
            gates,
            "code_gate",
            GateInput(project_path=self._project_path),
            notify,
        ):
            return self._finish(ctx)

        # 5. Reviewer
        review_result = self._run_agent(
            agents["reviewer"],
            AgentTask(
                description="review project",
                task_type="review",
                params={"target": str(self._project_path)},
            ),
        )
        ctx.review_report = json.loads(review_result.output) if review_result.output else {}
        ctx.stages.append(WorkflowStage(name="reviewer", success=review_result.success))
        notify(ctx.stages[-1])

        # 5b. Security gate — deterministic secret/unsafe scan
        if gates and not self._run_gate(
            ctx,
            gates,
            "security_gate",
            GateInput(project_path=self._project_path),
            notify,
        ):
            return self._finish(ctx)

        # 6. Tester
        if agents["tester"] is not None:
            tests_dir = self._project_path / "tests"
            if tests_dir.exists():
                test_result = self._run_agent(
                    agents["tester"],
                    AgentTask(
                        description="run test suite",
                        task_type="test",
                        params={"target": str(tests_dir), "dry_run": False},
                    ),
                )
                ctx.test_report = json.loads(test_result.output) if test_result.output else {}
            failed = (ctx.test_report or {}).get("failed", 0)
            ctx.stages.append(WorkflowStage(name="tester", success=failed == 0))
        else:
            failed = 0
            ctx.stages.append(WorkflowStage(name="tester", success=True, details={"skipped": True}))
        notify(ctx.stages[-1])
        if failed > 0:
            ctx.errors.append(f"Tester: {failed} test(s) failed")
            return self._finish(ctx)

        # 6b. Test gate — green iff failed == 0
        if gates and not self._run_gate(
            ctx,
            gates,
            "test_gate",
            GateInput(test_report=ctx.test_report),
            notify,
        ):
            return self._finish(ctx)

        # 7. Documentation
        if agents["documentation"] is not None:
            combined_report = {
                "summary": {
                    "passed": (ctx.test_report or {}).get("passed", 0),
                    "failed": failed,
                },
                "items": (ctx.review_report or {}).get("items", []),
            }
            doc_result = self._run_agent(
                agents["documentation"],
                AgentTask(
                    description="generate changelog fragment",
                    task_type="documentation",
                    params={"report": combined_report, "dry_run": False},
                ),
            )
            ctx.stages.append(WorkflowStage(name="documentation", success=doc_result.success))
        else:
            ctx.stages.append(
                WorkflowStage(name="documentation", success=True, details={"skipped": True})
            )
        notify(ctx.stages[-1])

        # 7b. Documentation gate — changelog/todo reflect the change
        if gates and not self._run_gate(
            ctx,
            gates,
            "documentation_gate",
            GateInput(project_path=self._project_path),
            notify,
        ):
            return self._finish(ctx)

        # 7c. Release gate — skeleton, only meaningful at release time
        if (
            gates
            and self._quality_config is not None
            and self._quality_config.environment == "release"
            and not self._run_gate(
                ctx,
                gates,
                "release_gate",
                GateInput(project_path=self._project_path),
                notify,
            )
        ):
            return self._finish(ctx)

        # 8. Git — stage and commit (push is never called)
        if agents["git"] is not None:
            stage_result = self._run_agent(
                agents["git"],
                AgentTask(description="stage changes", task_type="stage"),
            )
            ctx.commit = self._git_operation(stage_result)
            commit_result = self._run_agent(
                agents["git"],
                AgentTask(
                    description="commit changes",
                    task_type="commit",
                    params={"message": self._commit_factory(ctx)},
                ),
            )
            ctx.commit = self._git_operation(commit_result)
            ctx.stages.append(
                WorkflowStage(
                    name="git",
                    success=commit_result.success,
                    error=self._git_error(commit_result),
                )
            )
            notify(ctx.stages[-1])
            if not commit_result.success:
                ctx.errors.append(f"Git: commit failed: {self._git_error(commit_result)}")
        else:
            ctx.stages.append(WorkflowStage(name="git", success=True, details={"skipped": True}))
            notify(ctx.stages[-1])

        return self._finish(ctx)

    def _run_agent(self, agent, task: AgentTask, context=None) -> AgentResult:
        """Execute one agent through the single AgentExecutor boundary."""
        intent = getattr(context, "intent", None) if context is not None else None
        outcome = self._executor.execute(make_request(agent, task, context, intent=intent))
        if outcome.result is not None:
            return outcome.result
        error = outcome.error
        return AgentResult(
            success=False,
            errors=[error.message if error else "Agent execution failed"],
            error=error,
            error_code=error.code if error else None,
            status=outcome.status,
            agent=agent.name,
            task_id=task.task_id,
            correlation_id=task.correlation_id,
        )

    @staticmethod
    def _apply_workflow_intent(context) -> None:
        """Set the workflow intent on the shared context, respecting an override."""
        if context is None or getattr(context, "intent", None) is not None:
            return
        try:
            context.intent = WORKFLOW_INTENT
        except AttributeError:
            logger.warning("Workflow intent not attached: context has no settable 'intent'")

    @staticmethod
    def _git_operation(result: AgentResult) -> dict | None:
        if not result.output:
            return None
        try:
            return json.loads(result.output)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _git_error(result: AgentResult) -> str | None:
        operation = WorkflowEngine._git_operation(result)
        if operation and operation.get("stderr"):
            return operation["stderr"].strip()
        return result.errors[0] if result.errors else None

    # ------------------------------------------------------------------
    # Quality gates
    # ------------------------------------------------------------------

    def _quality_active(self) -> bool:
        config = self._quality_config
        return config is not None and config.enabled

    def _gates(self) -> dict[str, QualityGate]:
        if not self._quality_active():
            return {}
        if self._quality_gates is not None:
            return self._quality_gates
        return {
            "code_gate": CodeGate(),
            "security_gate": SecurityGate(),
            "test_gate": TestGate(),
            "documentation_gate": DocumentationGate(),
            "release_gate": ReleaseGate(),
        }

    def _run_gate(
        self,
        ctx: _WorkflowContext,
        gates: dict[str, QualityGate],
        name: str,
        gate_input: GateInput,
        notify: Callable[[WorkflowStage], None],
    ) -> bool:
        """Run one gate and apply the policy. Returns False to stop the run."""
        gate = gates.get(name)
        if gate is None:
            stage = WorkflowStage(
                name=name, success=True, details={"skipped": True, "reason": "gate not configured"}
            )
            ctx.stages.append(stage)
            notify(stage)
            return True
        self._publish_quality(ctx, QUALITY_GATE_STARTED, {"gate": name})
        started = time.monotonic()
        try:
            result = asyncio.run(gate.run(gate_input))
        except Exception as exc:  # noqa: BLE001 - a crashed gate must not crash the workflow
            result = GateResult(status=GateStatus.ERROR, reason=f"gate crashed: {exc}")
        duration_ms = (time.monotonic() - started) * 1000

        details: dict = {"gate": result.to_dict()}
        policy = self._resolve_gate(name, result) if result.status is GateStatus.FAILED else None

        blocked = False
        overridden = False
        reason = result.reason
        if result.status is GateStatus.ERROR:
            blocked = True
            reason = reason or "gate error (fail-safe block)"
        elif result.status is GateStatus.FAILED:
            details["policy"] = policy.to_dict()
            blocked = policy.blocks()
            overridden = policy.overridden
            reason = policy.reason if blocked else f"{result.reason}; {policy.reason}"
        elif result.status is GateStatus.SKIPPED:
            details["skipped"] = True

        payload = {
            "gate": name,
            "status": result.status.value,
            "duration_ms": duration_ms,
            "findings": _findings_counts(result),
            "blocked": blocked,
            "overridden": overridden,
            "reason": reason,
        }
        topic = QUALITY_GATE_BLOCKED if blocked else QUALITY_GATE_COMPLETED
        self._publish_quality(ctx, topic, payload)

        if blocked:
            stage = WorkflowStage(name=name, success=False, details=details, error=reason)
            ctx.stages.append(stage)
            notify(stage)
            ctx.errors.append(f"{name}: blocked by policy - {reason}")
            return False
        stage = WorkflowStage(name=name, success=True, details=details)
        ctx.stages.append(stage)
        notify(stage)
        return True

    def _resolve_gate(self, name: str, result: GateResult) -> DecisionResult:
        config = self._quality_config
        return resolve_decision(
            [finding.severity for finding in result.findings],
            gate=name,
            environment=config.environment if config else "dev",
            policy=config.policy if config else None,
            overrides=config.overrides if config else None,
        )

    def _finish(self, ctx: _WorkflowContext) -> WorkflowResult:
        ctx.finished_at = datetime.now(UTC).isoformat()
        if ctx.quality_active:
            self._publish_quality(
                ctx,
                QUALITY_COMPLETED,
                {"success": not ctx.errors, "errors": list(ctx.errors)},
            )
        return WorkflowResult.from_context(ctx)

    def _publish_quality(self, ctx: _WorkflowContext, topic: str, payload: dict) -> None:
        if self._bus is None:
            return
        event_payload = dict(payload)
        event_payload["correlation_id"] = str(ctx.run_id)
        self._bus.publish(topic, event_payload, correlation_id=event_payload["correlation_id"])

    def _run_research(self, ctx: _WorkflowContext, task: Task, context, notify) -> None:
        result = self._run_agent(
            self._agents["research"],
            AgentTask(
                description=task.description,
                task_type="research",
                params={"scope": "mixed"},
                correlation_id=str(ctx.run_id),
            ),
            context,
        )
        if not result.success:
            ctx.stages.append(
                WorkflowStage(
                    name="research",
                    success=False,
                    error=result.errors[0] if result.errors else "Research failed",
                )
            )
            notify(ctx.stages[-1])
            return

        try:
            serialized = json.loads(result.output)
        except json.JSONDecodeError:
            logger.warning("Research front-gate returned invalid JSON output")
            serialized = {}
        ctx.research_result = serialized
        try:
            context.research = serialized
        except AttributeError:
            logger.warning("Research result not attached: context has no settable 'research'")
        ctx.stages.append(
            WorkflowStage(
                name="research",
                success=True,
                details={
                    "status": serialized.get("status"),
                    "summary_short": serialized.get("summary_short"),
                    "sources": len(serialized.get("sources", [])),
                    "findings": len(serialized.get("findings", [])),
                },
            )
        )
        notify(ctx.stages[-1])

    @staticmethod
    def _build_branch(run_id: int, goal: str) -> str:
        slug = _SLUG_RE.sub("-", goal.lower()).strip("-")
        return f"feature/{slug}-{run_id}"
