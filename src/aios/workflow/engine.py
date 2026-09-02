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
    RESEARCH_COMPLETED,
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
from aios.security.resolver import effective_permissions
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
_GATE_TIMEOUT_SECONDS = 30.0

# Conventional-commit types whose success does not require a code change in
# src/ or tests/. Documentation and release-metadata tasks remain exceptions.
_NON_IMPLEMENTATION_TYPES = frozenset({"docs", "chore", "release", "meta"})

# Directories that count as a "relevant" implementation change for #79.
_RELEVANT_PREFIXES = ("src/", "tests/")

logger = logging.getLogger("aios.workflow")

OPTIONAL_AGENTS = ("tester", "documentation", "git", "research")

_STAGE_AGENT = {
    "planner": "planner",
    "reviewer": "reviewer",
    "tester": "tester",
    "documentation": "documentation",
    "git": "git",
    "research": "research",
}


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

    def execute(
        self,
        task: Task,
        context,
        on_stage: Callable[[WorkflowStage], None] | None = None,
        commit_factory: Callable[[_WorkflowContext], str] | None = None,
        create_branch: bool = True,
    ) -> WorkflowResult:
        """Run the synchronous workflow, sharing one loop across quality gates."""
        gates = self._gates()
        gate_loop = asyncio.new_event_loop() if gates else None
        try:
            return self._execute(
                task,
                context,
                on_stage,
                commit_factory,
                create_branch,
                gate_loop,
            )
        finally:
            if gate_loop is not None:
                self._close_gate_loop(gate_loop)

    def _execute(  # noqa: PLR0911, PLR0912, PLR0913, PLR0915, PLR0917 - linear pipeline
        self,
        task: Task,
        context,
        on_stage: Callable[[WorkflowStage], None] | None = None,
        commit_factory: Callable[[_WorkflowContext], str] | None = None,
        create_branch: bool = True,
        gate_loop: asyncio.AbstractEventLoop | None = None,
    ) -> WorkflowResult:
        notify = on_stage or (lambda stage: None)
        cf = commit_factory or self._commit_factory
        ctx = _WorkflowContext(
            task=task,
            run_id=self._run_ids.next(),
            goal=task.description,
            started_at=datetime.now(UTC).isoformat(),
        )
        self._apply_workflow_intent(context)
        ctx.intent = getattr(context, "intent", None) if context is not None else None
        agents = self._agents
        gates = self._gates()
        ctx.quality_active = bool(gates)
        if gates:
            environment = self._quality_config.environment if self._quality_config else "dev"
            self._publish_quality(ctx, QUALITY_STARTED, {"environment": environment})

        # 0–1. Research + Planner
        subtasks, early = self._run_plan_phase(ctx, agents, task, context, notify)
        if early is not None:
            return early

        # 2. Git — create the run branch before any scheduler persistence
        if agents["git"] is not None and create_branch:
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
        early = self._run_developer_phase(ctx, agents, subtasks, context, gates, notify, gate_loop)
        if early is not None:
            return early

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
            gate_loop,
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
            gate_loop,
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
            gate_loop,
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
                gate_loop,
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
                    params={"message": cf(ctx)},
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

    def _run_plan_phase(
        self, ctx: _WorkflowContext, agents: dict, task: Task, context, notify
    ) -> tuple[list[dict], WorkflowResult | None]:
        """Research front-gate (optional) and planner execution.

        Returns ``(subtasks, None)`` on success or ``([], result)`` on
        failure (caller must return the result immediately).
        """
        if agents["research"] is not None:
            self._run_research(ctx, task, context, notify)

        plan_result = self._run_agent(agents["planner"], coerce_task(task), context)
        if not plan_result.success:
            ctx.stages.append(WorkflowStage(name="planner", success=False))
            notify(ctx.stages[-1])
            ctx.errors.append(plan_result.errors[0] if plan_result.errors else "Planner failed")
            return [], self._finish(ctx)
        ctx.plan = json.loads(plan_result.output)
        subtasks = ctx.plan.get("subtasks", [])
        ctx.subtask_count = len(subtasks)
        ctx.stages.append(WorkflowStage(name="planner", success=True, details={"plan": ctx.plan}))
        notify(ctx.stages[-1])
        return subtasks, None

    def _run_developer_phase(  # noqa: PLR0913, PLR0917
        self,
        ctx: _WorkflowContext,
        agents: dict,
        subtasks: list[dict],
        context,
        gates: dict,
        notify,
        gate_loop: asyncio.AbstractEventLoop | None,
    ) -> WorkflowResult | None:
        """Per-subtask developer loop followed by the code gate.

        Returns ``None`` on success or a ``WorkflowResult`` on failure
        (caller must return it immediately).
        """
        git = agents["git"]
        before = self._changed_files(git) if git is not None else []
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
                        details={
                            "description": subtask["description"],
                            "subtask_total": len(subtasks),
                        },
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
                    details={
                        "description": subtask["description"],
                        "subtask_total": len(subtasks),
                    },
                )
            )
            notify(ctx.stages[-1])

        # Detect changes actually produced by the developer (before/after delta),
        # so a pre-existing dirty working tree cannot cause a false positive.
        if git is not None:
            after = self._changed_files(git)
            produced = sorted(set(after) - set(before))
            ctx.changed_files = produced
            relevant = any(path.startswith(_RELEVANT_PREFIXES) for path in produced)
            ctx.produced_change = relevant
            for stage in ctx.stages:
                if stage.name.startswith("developer:"):
                    stage.details = {**stage.details, "files": list(produced)}
            if self._is_implementation_task(ctx.task) and not relevant:
                reason = (
                    "Developer produced no changes in src/ or tests/ (no-op); "
                    f"changed files: {produced or 'none'}"
                )
                if ctx.cards:
                    agents["scheduler"].block_card(ctx.cards[-1].id, reason=reason)
                ctx.stages.append(
                    WorkflowStage(
                        name="developer:noop",
                        success=False,
                        error=reason,
                        details={"changed_files": produced},
                    )
                )
                notify(ctx.stages[-1])
                ctx.errors.append(reason)
                return self._finish(ctx)

        if gates and not self._run_gate(
            ctx,
            gates,
            "code_gate",
            GateInput(project_path=self._project_path),
            notify,
            gate_loop,
        ):
            return self._finish(ctx)
        return None

    @staticmethod
    def _is_implementation_task(task: Task) -> bool:
        """A task is an implementation task unless its type is a docs/release one."""
        return (task.task_type or "code") not in _NON_IMPLEMENTATION_TYPES

    @staticmethod
    def _changed_files(git) -> list[str]:
        """Reuse the GitAgent change-set query; best-effort returns [] on error."""
        try:
            return list(git._changed_files())
        except Exception:  # noqa: BLE001 - a failed status probe must not crash the run
            return []

    @staticmethod
    def _apply_workflow_intent(context) -> None:
        """Set the workflow intent on the shared context, respecting an override."""
        if context is None or getattr(context, "intent", None) is not None:
            return
        try:
            context.intent = WORKFLOW_INTENT
        except AttributeError:
            logger.warning("Workflow intent not attached: context has no settable 'intent'")

    def _enrich_stage_effective(self, ctx: _WorkflowContext) -> None:
        """Expose the effective permissions and intent on each agent stage."""
        if ctx.intent is None:
            return
        for stage in ctx.stages:
            agent_name = _STAGE_AGENT.get(stage.name)
            if stage.name.startswith("developer:"):
                agent_name = "developer"
            if agent_name is None:
                continue
            agent = self._agents.get(agent_name)
            if agent is None:
                continue
            effective = effective_permissions(ctx.intent, agent.capabilities)
            if not effective:
                continue
            details = dict(stage.details)
            details["effective"] = sorted(effective)
            details.setdefault(
                "intent",
                {"name": ctx.intent.name or "", "source": ctx.intent.source or ""},
            )
            stage.details = details

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

    def _run_gate(  # noqa: PLR0913, PLR0917 - gate context and lifecycle are explicit
        self,
        ctx: _WorkflowContext,
        gates: dict[str, QualityGate],
        name: str,
        gate_input: GateInput,
        notify: Callable[[WorkflowStage], None],
        gate_loop: asyncio.AbstractEventLoop,
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
            result = gate_loop.run_until_complete(
                asyncio.wait_for(gate.run(gate_input), timeout=_GATE_TIMEOUT_SECONDS)
            )
        except TimeoutError:
            result = GateResult(
                status=GateStatus.ERROR,
                reason=f"gate timed out after {_GATE_TIMEOUT_SECONDS:g}s",
                metadata={"timeout_seconds": _GATE_TIMEOUT_SECONDS},
            )
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

    @staticmethod
    def _close_gate_loop(loop: asyncio.AbstractEventLoop) -> None:
        """Cancel leaked gate tasks before closing the per-workflow loop."""
        if loop.is_closed():
            return
        try:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            loop.close()

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
        self._enrich_stage_effective(ctx)
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

    def _publish_research(self, ctx: _WorkflowContext, serialized: dict) -> None:
        if self._bus is None:
            return
        memory_candidates = serialized.get("memory_candidates", [])
        payload = {
            "correlation_id": str(ctx.run_id),
            "memory_candidates": memory_candidates,
            "findings": len(serialized.get("findings", [])),
            "sources": len(serialized.get("sources", [])),
        }
        self._bus.publish(RESEARCH_COMPLETED, payload, correlation_id=str(ctx.run_id))

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
        self._publish_research(ctx, serialized)

    @staticmethod
    def _build_branch(run_id: int, goal: str) -> str:
        slug = _SLUG_RE.sub("-", goal.lower()).strip("-")[:50].strip("-")
        if not slug:
            slug = "task"
        return f"feature/{slug}-{run_id}"
