"""Kernel: bootstrap, lifecycle, and engine coordination."""

import logging
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal

from aios.agents.contracts import coerce_task
from aios.agents.executor import make_request
from aios.core.console import (
    render_engine,
    render_footer,
    render_header,
    render_row,
    render_section,
)
from aios.core.engine import Engine
from aios.core.profiler import Profiler, create_profiler
from aios.core.run_result import RunResult, StageSummary, stage_to_summary
from aios.core.task import Task

logger = logging.getLogger("aios.kernel")
INIT_ORDER = [
    "config",
    "context",
    "memory",
    "learning",
    "scheduler",
    "runtime",
    "developer",
    "planner",
    "workflow",
    "events",
    "telemetry",
    "knowledge",
    "security",
]


class Kernel:
    """Central hub of AiosDeck.  Registers engines and agents, wires the
    event bus, manages the lifecycle (start/shutdown), and routes CLI commands
    to the appropriate execution path (plan, plan-run, workflow)."""

    def __init__(self, project_path: str = ".") -> None:
        self.project_path = Path(project_path).resolve()
        self._engines: dict[str, Engine] = {}
        self._engine_status: dict[str, str] = {}
        self._errors: list[str] = []
        self._executor = None
        self._profiler: Profiler = create_profiler()

    @property
    def timings(self) -> dict:
        """Startup timing contract populated only when profiling is enabled."""
        return self._profiler.timings

    def register(self, engine: Engine) -> None:
        self._engines[engine.name] = engine

    def set_executor(self, executor) -> None:
        """Attach the single AgentExecutor execution boundary."""
        self._executor = executor

    def start(self, render_dashboard: bool = True, quiet: bool = False) -> None:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

        if not quiet:
            self._print_banner()
        self._inject_profiler()
        with self._profiler.measure_total():
            self._initialize_engines()
            self._wire_event_bus()
            self._enrich_context_with_memory()
            if render_dashboard:
                self._render_dashboard()

        if self._errors:
            logger.warning("\n Warnings:")
            for err in self._errors:
                logger.warning("   %s", err)

    def _inject_profiler(self) -> None:
        """Share the Kernel profiler with the ContextEngine before detection."""
        context = self._engines.get("context")
        if context is not None and hasattr(context, "set_profiler"):
            context.set_profiler(self._profiler)

    def shutdown(self) -> None:
        for name in reversed(INIT_ORDER):
            engine = self._engines.get(name)
            if engine:
                try:
                    engine.shutdown()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(" Error shutting down %s: %s", name, exc)

    def _initialize_engines(self) -> None:
        for name in INIT_ORDER:
            engine = self._engines.get(name)
            if engine is None:
                self._engine_status[name] = "not installed"
                continue

            try:
                with self._profiler.measure_engine(name):
                    engine.initialize()
                if engine.health_check():
                    self._engine_status[name] = "ready"
                else:
                    self._engine_status[name] = "degraded"
                    self._errors.append(f"{name}: health check failed")
            except Exception as exc:  # noqa: BLE001
                self._engine_status[name] = "error"
                self._errors.append(f"{name}: {exc}")

    def _print_banner(self) -> None:
        logger.info(render_header())
        logger.info(render_row("Project", str(self.project_path)))
        if self.project_path.name != self.project_path.resolve().name:
            logger.info(render_row("Name", self.project_path.name))

    def _render_dashboard(self) -> None:
        logger.info(render_section("Engines"))
        for name in INIT_ORDER:
            status = self._engine_status.get(name, "unknown")
            logger.info(render_engine(name, status))

        self._render_workflow_pipeline()

        logger.info(render_section("Status"))
        if self._errors:
            logger.info(" %-14s Degraded (%d warning(s))", "Health", len(self._errors))
        else:
            logger.info(" %-14s Healthy", "Health")

        logger.info(render_footer())

    def _render_workflow_pipeline(self) -> None:
        """Show which pipeline stages are available and which optionals are absent."""
        workflow = self._engines.get("workflow")
        if workflow is None:
            return
        try:
            health = workflow.health_check()
        except Exception:  # noqa: BLE001 - a broken health probe must not crash the dashboard
            return
        agents = getattr(health, "agents", None)
        if not isinstance(agents, dict):
            return
        optional = set(getattr(health, "optional", []) or [])
        logger.info(render_section("Workflow Pipeline"))
        for name, available in agents.items():
            suffix = " (optional)" if name in optional else ""
            mark = "✓" if available else "—"
            logger.info(" %-24s %s", f"{name}{suffix}", mark)
        missing = [name for name, ok in agents.items() if not ok and name in optional]
        if missing:
            logger.info(" Optional not installed: %s", ", ".join(missing))

    def status(self) -> dict:
        return {
            "project": str(self.project_path),
            "engines": dict(self._engine_status),
            "errors": list(self._errors),
        }

    def get_context(self):
        engine = self._engines.get("context")
        if engine and engine.context:
            return engine.context
        return None

    def get_engine(self, name: str):
        return self._engines.get(name)

    def run(  # noqa: PLR0913, PLR0917
        self,
        task: Task,
        context,
        mode: Literal["plan", "plan-run"] = "plan",
        on_stage: Callable[[StageSummary], None] | None = None,
        commit_factory: Callable[[Any], str] | None = None,
        create_branch: bool = True,
    ) -> RunResult:
        """Canonical task entry point.

        ``mode="plan"`` runs the planner only; ``mode="plan-run"`` runs the full
        workflow pipeline. The Kernel resolves the right engine internally, so
        callers never reach into individual agents. Failures are normalized into
        ``RunResult.errors`` with a friendly message. Agent work always routes
        through the single AgentExecutor boundary.

        ``commit_factory`` and ``create_branch`` are forwarded to the workflow
        engine when mode is ``plan-run``.
        """
        if mode == "plan-run":
            return self._run_workflow(task, context, on_stage, commit_factory, create_branch)
        return self._run_plan(task, context)

    def run_agent(self, name: str, task: Task, context=None) -> RunResult:
        """Run a single agent through the executor boundary (used by the CLI)."""
        agent = self._engines.get(name)
        if agent is None:
            return RunResult(success=False, errors=(f"Agent '{name}' not available.",))
        if self._executor is None:
            return RunResult(success=False, errors=("Executor not available.",))
        try:
            outcome = self._executor.execute(make_request(agent, coerce_task(task), context))
        except Exception as exc:  # noqa: BLE001 - surface a friendly message
            return RunResult(success=False, errors=(f"{name} failed: {exc}",))
        return self._run_result_from_outcome(outcome)

    def _run_plan(self, task: Task, context) -> RunResult:
        planner = self._engines.get("planner")
        if planner is None:
            return RunResult(success=False, errors=("Planner agent not available.",))
        if self._executor is None:
            return RunResult(success=False, errors=("Executor not available.",))
        try:
            outcome = self._executor.execute(make_request(planner, coerce_task(task), context))
        except Exception as exc:  # noqa: BLE001 - surface a friendly message
            return RunResult(success=False, errors=(f"Planning failed: {exc}",))
        return self._run_result_from_outcome(outcome)

    @staticmethod
    def _run_result_from_outcome(outcome) -> RunResult:
        if outcome.result is not None:
            return RunResult.from_agent(outcome.result)
        message = outcome.error.message if outcome.error else "Agent execution failed"
        return RunResult(success=False, errors=(message,))

    def _run_workflow(
        self,
        task: Task,
        context,
        on_stage: Callable[[StageSummary], None] | None,
        commit_factory: Callable[[Any], str] | None = None,
        create_branch: bool = True,
    ) -> RunResult:
        workflow = self._engines.get("workflow")
        if workflow is None:
            return RunResult(success=False, errors=("Workflow engine not available.",))
        wrapped: Callable | None = None
        if on_stage is not None:
            wrapped = lambda stage: on_stage(stage_to_summary(stage))  # noqa: E731
        try:
            result = workflow.execute(
                task,
                context,
                on_stage=wrapped,
                commit_factory=commit_factory,
                create_branch=create_branch,
            )
        except Exception as exc:  # noqa: BLE001 - surface a friendly message
            return RunResult(success=False, errors=(f"Workflow failed: {exc}",))
        return RunResult.from_workflow(result)

    def _wire_event_bus(self) -> None:
        events = self._engines.get("events")
        scheduler = self._engines.get("scheduler")
        runtime = self._engines.get("runtime")
        telemetry = self._engines.get("telemetry")
        workflow = self._engines.get("workflow")
        learning = self._engines.get("learning")
        if events is not None and events.bus is not None:
            if scheduler is not None:
                scheduler.set_event_bus(events.bus)
            if runtime is not None:
                runtime.set_event_bus(events.bus)
            if self._executor is not None:
                self._executor.set_event_bus(events.bus)
            if telemetry is not None:
                telemetry.set_event_bus(events.bus)
            if workflow is not None:
                workflow.set_event_bus(events.bus)
            if learning is not None:
                learning.set_event_bus(events.bus)

    def _enrich_context_with_memory(self) -> None:
        memory = self._engines.get("memory")
        context = self._engines.get("context")
        if memory and context and context.context and self._engine_status.get("memory") == "ready":
            with suppress(Exception):
                memory.enrich_context(context.context)
