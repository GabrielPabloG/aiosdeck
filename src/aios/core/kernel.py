"""Kernel: bootstrap, lifecycle, and engine coordination."""

import logging
from contextlib import suppress
from pathlib import Path

from aios.core.console import (
    render_engine,
    render_footer,
    render_header,
    render_row,
    render_section,
)
from aios.core.engine import Engine

logger = logging.getLogger("aios.kernel")

INIT_ORDER = [
    "config",
    "context",
    "memory",
    "scheduler",
    "runtime",
    "developer",
    "planner",
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

        logger.info(render_section("Status"))
        if self._errors:
            logger.info(" %-14s Degraded (%d warning(s))", "Health", len(self._errors))
        else:
            logger.info(" %-14s Healthy", "Health")

        logger.info(render_footer())

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

    def _enrich_context_with_memory(self) -> None:
        memory = self._engines.get("memory")
        context = self._engines.get("context")
        if memory and context and context.context and self._engine_status.get("memory") == "ready":
            with suppress(Exception):
                memory.enrich_context(context.context)
