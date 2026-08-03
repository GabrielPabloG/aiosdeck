"""CLI entry point for the aios command."""

import argparse
import json
import logging
import signal
import sys
from pathlib import Path

from aios import __version__
from aios.agents.developer import DeveloperAgent
from aios.cli.commands import COMMANDS
from aios.cli.completion import complete
from aios.config import ConfigEngine
from aios.context import ContextEngine
from aios.core import Kernel
from aios.core.console import render_row, render_section
from aios.events import EventsEngine
from aios.integrations.projdesk import (
    ProjDeskClient,
    ProjDeskError,
    ProjectAmbiguous,
    ProjectNotFound,
)
from aios.memory import MemoryEngine
from aios.runtime import RuntimeEngine
from aios.security import SecurityEngine

VERSION_TEXT = f"AiosDeck v{__version__}"

_active_kernel: Kernel | None = None


def _handle_signal(signum: int, frame: object) -> None:  # noqa: ARG001
    print("\nShutting down...", file=sys.stderr)
    if _active_kernel is not None:
        _active_kernel.shutdown()
    sys.exit(0)


def main() -> None:  # noqa: PLR0911
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    parser = argparse.ArgumentParser(
        prog="aios",
        description="The AI Operating System for Developers.",
        add_help=False,
    )
    parser.add_argument("--help", "-h", action="store_true")
    parser.add_argument("--version", "-V", action="store_true")
    parser.add_argument("command", nargs="?", default=None)
    parser.add_argument("args", nargs=argparse.REMAINDER)

    args = parser.parse_args()

    if args.help:
        _print_help()
        sys.exit(0)

    if args.version:
        print(VERSION_TEXT)
        sys.exit(0)

    if args.command is None:
        try:
            project_path = _resolve_project([])
            _cmd_dashboard(project_path)
        except (ProjectNotFound, ProjectAmbiguous, ProjDeskError) as exc:
            _error(str(exc))
        return

    cmd_name = args.command

    if cmd_name == "__complete":
        _print_completions(args.args)
        return

    if cmd_name == "help":
        _print_help()
        return

    try:
        if cmd_name == "doctor":
            project_args = [a for a in args.args if a != "--json"]
            project_path = _resolve_project(project_args)
            _cmd_doctor(project_path, args.args)
            return

        if cmd_name in ("start", "status"):
            project_path = _resolve_project(args.args)
            _cmd_dashboard(project_path)
            return

        if cmd_name == "exit":
            project_path = _resolve_project(args.args)
            _cmd_exit(project_path)
            return

        if cmd_name in COMMANDS:
            project_path = _resolve_project([])
            _dispatch(COMMANDS[cmd_name], args.args, project_path)
            return
    except (ProjectNotFound, ProjectAmbiguous, ProjDeskError) as exc:
        _error(str(exc))
        return

    _error(f"Unknown command: {cmd_name}\nRun 'aios help' for available commands.")


def _resolve_project(args: list[str]) -> Path:
    candidate = args[0] if args else None
    if candidate is None:
        return Path.cwd()

    path = Path(candidate)
    if path.is_dir():
        return path.resolve()

    return ProjDeskClient().resolve(candidate)


def _dispatch(cmd, raw_args: list[str], project_path: Path) -> None:
    if not raw_args and cmd.execute is not None:
        cmd.execute(raw_args, project_path, _create_kernel)
        return

    if not raw_args:
        _print_command_help(cmd)
        return

    sub_name = raw_args[0]
    remaining = raw_args[1:]

    sub = cmd.subcommands.get(sub_name)
    if sub is None:
        for c in cmd.subcommands.values():
            if sub_name in c.aliases:
                sub = c
                break

    if sub is not None:
        if sub.subcommands or sub.execute is not None:
            _dispatch(sub, remaining, project_path)
        elif cmd.execute is not None:
            cmd.execute(raw_args, project_path, _create_kernel)
        else:
            _print_command_help(sub)
        return

    if cmd.execute is not None:
        cmd.execute(raw_args, project_path, _create_kernel)
        return

    _error(f"Unknown subcommand: {sub_name}")


def _print_help() -> None:
    print(f"{VERSION_TEXT}")
    print("The AI Operating System for Developers.")
    print()
    print("Usage:")
    print("  aios                  Show dashboard")
    print("  aios doctor [--json]    Run diagnostics")
    print("  aios memory <cmd>     Manage project knowledge")
    print("  aios help             Show this help")
    print()
    print("Commands:")
    _print_command_list(COMMANDS, indent=2)
    print()
    print("Aliases:")
    print("  start, status         Show dashboard")
    print("  exit                  Shut down gracefully")
    print()
    print("Project: https://github.com/GabrielPabloG/aiosdeck")


def _print_command_list(commands: dict, indent: int = 0) -> None:
    prefix = " " * indent
    for name, cmd in commands.items():
        print(f"{prefix}{name:<20} {cmd.description}")
        if cmd.aliases:
            print(f"{prefix}  aliases: {', '.join(cmd.aliases)}")
        if cmd.subcommands:
            _print_command_list(cmd.subcommands, indent=indent + 2)


def _print_command_help(cmd) -> None:
    print(f"{cmd.name} — {cmd.description}")
    if cmd.aliases:
        print(f"Aliases: {', '.join(cmd.aliases)}")
    if cmd.subcommands:
        print()
        print("Subcommands:")
        _print_command_list(cmd.subcommands, indent=2)


def _print_completions(tokens: list[str]) -> None:
    suggestions = complete(tokens)
    for s in suggestions:
        print(s)


def _cmd_dashboard(project_path: Path) -> None:
    kernel = _create_kernel(project_path)
    kernel.start()


def _cmd_doctor(project_path: Path, raw_args: list[str] | None = None) -> None:
    as_json = "--json" in (raw_args or [])

    kernel = _create_kernel(project_path)
    kernel.start()

    status = kernel.status()

    if as_json:
        context = kernel.get_context()
        if context:
            status["context"] = {
                "language": context.project.language,
                "linter": context.tools.linter,
                "formatter": context.tools.formatter,
                "test_runner": context.tools.test_runner,
                "git_branch": context.git.branch,
                "git_status": context.git.status,
                "opencode": context.runtime.opencode,
                "ai_jail": context.runtime.ai_jail,
            }
        print(json.dumps(status, indent=2))
        return

    logger = logging.getLogger("aios")
    context = kernel.get_context()
    if context:
        logger.info(render_section("Doctor"))
        logger.info(render_row("Language", context.project.language))
        logger.info(render_row("Tools", context.tools.linter or "none"))
        logger.info(render_row("Git", f"{context.git.branch} ({context.git.status})"))
        logger.info(
            render_row(
                "OpenCode",
                "installed" if context.runtime.opencode else "not found",
            )
        )
        logger.info(render_row("ai-jail", "installed" if context.runtime.ai_jail else "not found"))

    errors = status.get("errors", [])
    if errors:
        logger.warning("\nWarnings:")
        for err in errors:
            logger.warning(f"  {err}")


def _cmd_exit(project_path: Path) -> None:
    kernel = _create_kernel(project_path)
    kernel.shutdown()


def _create_kernel(project_path: Path) -> Kernel:
    global _active_kernel  # noqa: PLW0603
    kernel = Kernel(project_path=str(project_path))
    kernel.register(ConfigEngine(project_path=project_path))
    kernel.register(ContextEngine(project_path=project_path))
    kernel.register(MemoryEngine(project_path=project_path))
    runtime = RuntimeEngine()
    kernel.register(runtime)
    kernel.register(DeveloperAgent(runtime))
    kernel.register(EventsEngine())
    kernel.register(SecurityEngine(project_path=project_path))
    _active_kernel = kernel
    return kernel


def _error(msg: str) -> None:
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)
