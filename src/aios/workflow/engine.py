"""WorkflowEngine — linear orchestrator for the agent pipeline.

Runs Planner → Git(branch) → Scheduler → Developer → Reviewer → Tester →
Documentation → Git(commit) through public APIs only. The engine holds no
business logic: it calls agents and decides when to stop.
"""

import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from aios.agents.developer import DeveloperAgent
from aios.agents.documentation import DocumentationAgent
from aios.agents.git import GitAgent
from aios.agents.planner import PlannerAgent
from aios.agents.research import ResearchAgent
from aios.agents.reviewer import ReviewerAgent
from aios.agents.tester import TesterAgent
from aios.core.task import Task
from aios.research import ResearchTask
from aios.scheduler import KanbanEngine
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


class WorkflowEngine:
    name = "workflow"

    def __init__(  # noqa: PLR0913 - the agents are the fixed pipeline contract
        self,
        *,
        planner: PlannerAgent,
        scheduler: KanbanEngine,
        developer: DeveloperAgent,
        reviewer: ReviewerAgent,
        researcher: ResearchAgent | None = None,
        tester: TesterAgent | None = None,
        documentation: DocumentationAgent | None = None,
        git: GitAgent | None = None,
        project_path: Path | None = None,
        commit_factory: Callable[[_WorkflowContext], str] | None = None,
        run_ids: RunIdGenerator | None = None,
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

    def initialize(self) -> None:
        """No setup required."""

    def shutdown(self) -> None:
        """No cleanup required."""

    def health_check(self) -> WorkflowHealth:
        return WorkflowHealth(
            agents={name: agent is not None for name, agent in self._agents.items()},
            optional=self._optional_agents,
        )

    def execute(  # noqa: PLR0912, PLR0915 - linear pipeline with per-stage handling
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
        agents = self._agents

        # 0. Research — optional front-gate. Only runs when a researcher is
        # injected; its structured result feeds the planner/developer context.
        if agents["research"] is not None:
            self._run_research(ctx, task, context, notify)

        # 1. Planner
        plan_result = agents["planner"].execute(task, context)
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
            branch_op = agents["git"].create_branch(branch)
            ctx.stages.append(
                WorkflowStage(
                    name="git",
                    success=branch_op.returncode == 0,
                    error=branch_op.stderr or None,
                )
            )
            notify(ctx.stages[-1])
            if branch_op.returncode != 0:
                ctx.errors.append(
                    f"Git: failed to create branch {branch}: {branch_op.stderr.strip()}"
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
            dev_task = Task(
                description=subtask["description"], task_type=subtask.get("type", "code")
            )
            dev_result = agents["developer"].execute(dev_task, context)
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

        # 5. Reviewer
        ctx.review_report = agents["reviewer"].review(target=str(self._project_path))
        ctx.stages.append(WorkflowStage(name="reviewer", success=True))
        notify(ctx.stages[-1])

        # 6. Tester
        if agents["tester"] is not None:
            tests_dir = self._project_path / "tests"
            if tests_dir.exists():
                ctx.test_report = agents["tester"].run(target=str(tests_dir), dry_run=False)
            failed = (ctx.test_report or {}).get("failed", 0)
            ctx.stages.append(WorkflowStage(name="tester", success=failed == 0))
        else:
            failed = 0
            ctx.stages.append(WorkflowStage(name="tester", success=True, details={"skipped": True}))
        notify(ctx.stages[-1])
        if failed > 0:
            ctx.errors.append(f"Tester: {failed} test(s) failed")
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
            ctx.fragment = agents["documentation"].generate_changelog_fragment(
                combined_report, dry_run=False
            )
            ctx.stages.append(WorkflowStage(name="documentation", success=True))
        else:
            ctx.stages.append(
                WorkflowStage(name="documentation", success=True, details={"skipped": True})
            )
        notify(ctx.stages[-1])

        # 8. Git — stage and commit (push is never called)
        if agents["git"] is not None:
            agents["git"].stage()
            ctx.commit = agents["git"].commit(self._commit_factory(ctx))
            ctx.stages.append(
                WorkflowStage(
                    name="git",
                    success=ctx.commit.returncode == 0,
                    error=ctx.commit.stderr or None,
                )
            )
            notify(ctx.stages[-1])
            if ctx.commit.returncode != 0:
                ctx.errors.append(f"Git: commit failed: {ctx.commit.stderr.strip()}")
        else:
            ctx.stages.append(WorkflowStage(name="git", success=True, details={"skipped": True}))
            notify(ctx.stages[-1])

        return self._finish(ctx)

    def _finish(self, ctx: _WorkflowContext) -> WorkflowResult:
        ctx.finished_at = datetime.now(UTC).isoformat()
        return WorkflowResult.from_context(ctx)

    def _run_research(self, ctx: _WorkflowContext, task: Task, context, notify) -> None:
        packet = getattr(context, "to_dict", lambda: {})()
        research_task = ResearchTask(
            question=task.description,
            scope="mixed",
            context_packet=packet,
        )
        try:
            result = self._agents["research"].research(research_task)
        except Exception as exc:  # noqa: BLE001 - research is advisory, never blocks the pipeline
            logger.warning("Research front-gate failed: %s", exc)
            ctx.stages.append(WorkflowStage(name="research", success=False, error=str(exc)))
            notify(ctx.stages[-1])
            return

        serialized = result.to_dict()
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
                    "status": result.status,
                    "summary_short": result.summary_short,
                    "sources": len(result.sources),
                    "findings": len(result.findings),
                },
            )
        )
        notify(ctx.stages[-1])

    @staticmethod
    def _build_branch(run_id: int, goal: str) -> str:
        slug = _SLUG_RE.sub("-", goal.lower()).strip("-")
        return f"feature/{slug}-{run_id}"
