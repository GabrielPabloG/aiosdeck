"""Kernel: bootstrap, lifecycle, and engine coordination."""

import logging
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Literal

from aios.core.console import (
    render_engine,
    render_footer,
    render_header,
    render_row,
    render_section,
)
from aios.core.engine import Engine
from aios.core.run_result import RunResult, StageSummary, stage_to_summary
from aios.core.task import Task

logger = logging.getLogger("aios.kernel")

INIT_ORDER = [
    "config",
    "context",
    "memory",
    "scheduler",
    "runtime",
    "developer",
    "planner",
    "workflow",
    "events",
    "security",
]


class Kernel:
    def __init__(self, project_path: str = ".") -> None:
        self.project_path = Path(project_path).resolve()
        self._engines: dict[str, Engine] = {}
        self._engine_status: dict[str, str] = {}
        self._errors: list[str] = []

    def register(self, engine: Engine) -> None:
        self._engines[engine.name] = engine

    def start(self) -> None:
        logging.basicConfig(level=logging.INFO, format="%(message)s")

        self._print_banner()
        self._initialize_engines()
        self._wire_event_bus()
        self._enrich_context_with_memory()
        self._render_dashboard()

        if self._errors:
            logger.warning("\n Warnings:")
            for err in self._errors:
                logger.warning("   %s", err)

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

    def run(
        self,
        task: Task,
        context,
        mode: Literal["plan", "plan-run"] = "plan",
        on_stage: Callable[[StageSummary], None] | None = None,
    ) -> RunResult:
        """Canonical task entry point.

        ``mode="plan"`` runs the planner only; ``mode="plan-run"`` runs the full
        workflow pipeline. The Kernel resolves the right engine internally, so
        callers never reach into individual agents. Failures are normalized into
        ``RunResult.errors`` with a friendly message.
        """
        if mode == "plan-run":
            return self._run_workflow(task, context, on_stage)
        return self._run_plan(task, context)

    def _run_plan(self, task: Task, context) -> RunResult:
        planner = self._engines.get("planner")
        if planner is None:
            return RunResult(success=False, errors=("Planner agent not available.",))
        try:
            result = planner.execute(task, context)
        except Exception as exc:  # noqa: BLE001 - surface a friendly message
            return RunResult(success=False, errors=(f"Planning failed: {exc}",))
        return RunResult.from_agent(result)

    def _run_workflow(
        self,
        task: Task,
        context,
        on_stage: Callable[[StageSummary], None] | None,
    ) -> RunResult:
        workflow = self._engines.get("workflow")
        if workflow is None:
            return RunResult(success=False, errors=("Workflow engine not available.",))
        wrapped: Callable | None = None
        if on_stage is not None:
            wrapped = lambda stage: on_stage(stage_to_summary(stage))  # noqa: E731
        try:
            result = workflow.execute(task, context, on_stage=wrapped)
        except Exception as exc:  # noqa: BLE001 - surface a friendly message
            return RunResult(success=False, errors=(f"Workflow failed: {exc}",))
        return RunResult.from_workflow(result)

    def _wire_event_bus(self) -> None:
        events = self._engines.get("events")
        scheduler = self._engines.get("scheduler")
        if events is not None and scheduler is not None and events.bus is not None:
            scheduler.set_event_bus(events.bus)

    def _enrich_context_with_memory(self) -> None:
        memory = self._engines.get("memory")
        context = self._engines.get("context")
        if memory and context and context.context and self._engine_status.get("memory") == "ready":
            with suppress(Exception):
                memory.enrich_context(context.context)
