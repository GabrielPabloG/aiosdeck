"""WorkflowEngine — linear orchestrator for the agent pipeline.

Runs Planner → Git(branch) → Scheduler → Developer → Reviewer → Tester →
Documentation → Git(commit) through public APIs only. The engine holds no
business logic: it calls agents and decides when to stop.
"""

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from aios.agents.developer import DeveloperAgent
from aios.agents.documentation import DocumentationAgent
from aios.agents.git import GitAgent
from aios.agents.planner import PlannerAgent
from aios.agents.reviewer import ReviewerAgent
from aios.agents.tester import TesterAgent
from aios.core.task import Task
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


class WorkflowEngine:
    name = "workflow"

    def __init__(  # noqa: PLR0913 - the seven agents are the fixed pipeline contract
        self,
        *,
        planner: PlannerAgent,
        scheduler: KanbanEngine,
        developer: DeveloperAgent,
        reviewer: ReviewerAgent,
        tester: TesterAgent,
        documentation: DocumentationAgent,
        git: GitAgent,
        project_path: Path | None = None,
        commit_factory: Callable[[_WorkflowContext], str] | None = None,
        run_ids: RunIdGenerator | None = None,
    ) -> None:
        agents = {
            "planner": planner,
            "scheduler": scheduler,
            "developer": developer,
            "reviewer": reviewer,
            "tester": tester,
            "documentation": documentation,
            "git": git,
        }
        for name, agent in agents.items():
            if agent is None:
                raise WorkflowConfigurationError(f"{name} agent is required")
        self._agents = agents
        self._project_path = project_path or Path.cwd()
        self._commit_factory = commit_factory or (lambda ctx: f"feat: {ctx.goal}")
        self._run_ids = run_ids or InMemoryRunIdGenerator()

    def initialize(self) -> None:
        """No setup required."""

    def shutdown(self) -> None:
        """No cleanup required."""

    def health_check(self) -> WorkflowHealth:
        return WorkflowHealth(
            agents={name: agent is not None for name, agent in self._agents.items()}
        )

    def execute(self, task: Task, context) -> WorkflowResult:
        ctx = _WorkflowContext(
            task=task,
            run_id=self._run_ids.next(),
            goal=task.description,
            started_at=datetime.now(UTC).isoformat(),
        )
        agents = self._agents

        # 1. Planner
        plan_result = agents["planner"].execute(task, context)
        ctx.stages.append(WorkflowStage(name="planner", success=plan_result.success))
        if not plan_result.success:
            ctx.errors.append(plan_result.errors[0] if plan_result.errors else "Planner failed")
            return self._finish(ctx)
        ctx.plan = json.loads(plan_result.output)
        subtasks = ctx.plan.get("subtasks", [])
        ctx.subtask_count = len(subtasks)

        # 2. Git — create the run branch before any scheduler persistence
        branch = self._build_branch(ctx.run_id, ctx.goal)
        branch_op = agents["git"].create_branch(branch)
        ctx.stages.append(
            WorkflowStage(
                name="git",
                success=branch_op.returncode == 0,
                error=branch_op.stderr or None,
            )
        )
        if branch_op.returncode != 0:
            ctx.errors.append(f"Git: failed to create branch {branch}: {branch_op.stderr.strip()}")
            return self._finish(ctx)
        ctx.branch = branch

        # 3. Scheduler
        board = agents["scheduler"].create_board(ctx.goal)
        ctx.board = board
        for subtask in subtasks:
            ctx.cards.append(agents["scheduler"].create_card(board.id, subtask["description"]))
        ctx.stages.append(WorkflowStage(name="scheduler", success=True))

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
                    WorkflowStage(name=f"developer:{i + 1}", success=False, error=error)
                )
                ctx.errors.append(
                    f"Developer [{subtask['description']}]: "
                    f"{dev_result.errors[0] if dev_result.errors else 'failed'}"
                )
                return self._finish(ctx)
            agents["scheduler"].complete_work(card.id)
            ctx.completed_count += 1
            ctx.stages.append(WorkflowStage(name=f"developer:{i + 1}", success=True))

        # 5. Reviewer
        ctx.review_report = agents["reviewer"].review(target=str(self._project_path))
        ctx.stages.append(WorkflowStage(name="reviewer", success=True))

        # 6. Tester
        tests_dir = self._project_path / "tests"
        if tests_dir.exists():
            ctx.test_report = agents["tester"].run(target=str(tests_dir), dry_run=False)
        failed = (ctx.test_report or {}).get("failed", 0)
        ctx.stages.append(WorkflowStage(name="tester", success=failed == 0))
        if failed > 0:
            ctx.errors.append(f"Tester: {failed} test(s) failed")
            return self._finish(ctx)

        # 7. Documentation
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

        # 8. Git — stage and commit (push is never called)
        agents["git"].stage()
        ctx.commit = agents["git"].commit(self._commit_factory(ctx))
        ctx.stages.append(
            WorkflowStage(
                name="git",
                success=ctx.commit.returncode == 0,
                error=ctx.commit.stderr or None,
            )
        )
        if ctx.commit.returncode != 0:
            ctx.errors.append(f"Git: commit failed: {ctx.commit.stderr.strip()}")

        return self._finish(ctx)

    def _finish(self, ctx: _WorkflowContext) -> WorkflowResult:
        ctx.finished_at = datetime.now(UTC).isoformat()
        return WorkflowResult.from_context(ctx)

    @staticmethod
    def _build_branch(run_id: int, goal: str) -> str:
        slug = _SLUG_RE.sub("-", goal.lower()).strip("-")
        return f"feature/{slug}-{run_id}"
