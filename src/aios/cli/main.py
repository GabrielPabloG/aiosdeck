"""CLI entry point for the aios command."""

import argparse
import json
import sys
from pathlib import Path

from aios import __version__
from aios.config import ConfigEngine
from aios.context import ContextEngine
from aios.core import Kernel
from aios.events import EventsEngine
from aios.runtime import RuntimeEngine
from aios.security import SecurityEngine

VERSION_TEXT = f"""\
AiosDeck v{__version__}
The AI Operating System for Developers.
"""

HELP_TEXT = f"""\
{VERSION_TEXT}

Usage:
  aios start              Start a development session
  aios start --project PATH  Start with explicit project path
  aios status             Show system status
  aios status --json      Machine-readable status
  aios exit               Shut down gracefully
  aios --version          Show version
  aios --help             Show this help

Project: https://github.com/GabrielPabloG/aiosdeck
Docs:    docs/
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="aios",
        description="The AI Operating System for Developers.",
        add_help=False,
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["start", "status", "exit"],
        help="Command to execute",
    )
    parser.add_argument(
        "--version", "-V", action="store_true", help="Show version and exit"
    )
    parser.add_argument(
        "--help", "-h", action="store_true", help="Show help and exit"
    )
    parser.add_argument(
        "--project", "-p", type=str, help="Explicit project path"
    )
    parser.add_argument(
        "--json", action="store_true", help="Machine-readable output"
    )

    args = parser.parse_args()

    if args.help:
        print(HELP_TEXT)
        sys.exit(0)

    if args.version:
        print(VERSION_TEXT.strip())
        sys.exit(0)

    if args.command is None:
        print(HELP_TEXT)
        sys.exit(0)

    project_path = Path(args.project) if args.project else Path.cwd()

    match args.command:
        case "start":
            _cmd_start(project_path)
        case "status":
            _cmd_status(project_path, args.json)
        case "exit":
            _cmd_exit(project_path)


def _create_kernel(project_path: Path) -> Kernel:
    kernel = Kernel(project_path=str(project_path))
    kernel.register(ConfigEngine(project_path=project_path))
    kernel.register(ContextEngine(project_path=project_path))
    kernel.register(RuntimeEngine())
    kernel.register(EventsEngine())
    kernel.register(SecurityEngine(project_path=project_path))
    return kernel


def _cmd_start(project_path: Path) -> None:
    kernel = _create_kernel(project_path)
    kernel.start()
    _render_context(kernel)
    _render_runtime(kernel)


def _cmd_status(project_path: Path, as_json: bool = False) -> None:
    kernel = _create_kernel(project_path)
    kernel.start()
    status = kernel.status()

    if as_json:
        print(json.dumps(status, indent=2))

    _render_context(kernel)
    _render_runtime(kernel)


def _cmd_exit(project_path: Path) -> None:
    kernel = _create_kernel(project_path)
    kernel.shutdown()


def _render_context(kernel: Kernel) -> None:
    import logging

    from aios.core.console import render_row, render_section

    context = kernel.get_context()
    if context is None:
        return

    logger = logging.getLogger("aios")
    logger.info(render_section("Context"))
    logger.info(render_row("Language", context.project.language))
    logger.info(render_row("Linter", context.tools.linter or "none"))
    logger.info(render_row("Formatter", context.tools.formatter or "none"))
    logger.info(render_row("Test runner", context.tools.test_runner or "none"))
    logger.info(render_row("Git", f"{context.git.branch} ({context.git.status})"))
    logger.info(render_row("Docker", "running" if context.docker.running else "not running"))
    logger.info(render_row("OpenCode", "installed" if context.runtime.opencode else "not found"))
    logger.info(render_row("ai-jail", "installed" if context.runtime.ai_jail else "not found"))
    logger.info(render_row("Skills", str(len(context.skills))))


def _render_runtime(kernel: Kernel) -> None:
    import logging

    from aios.core.console import render_row, render_section

    runtime_engine = kernel.get_engine("runtime")
    if runtime_engine is None:
        return

    logger = logging.getLogger("aios")
    logger.info(render_section("Runtime"))
    logger.info(render_row("Command", runtime_engine.command))
    logger.info(render_row("Sandbox", "active" if runtime_engine.has_sandbox else "inactive"))
