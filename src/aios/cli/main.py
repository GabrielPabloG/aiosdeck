"""CLI entry point for the aios command."""

import argparse
import signal
import sys
from pathlib import Path

from aios import __version__
from aios.agents.developer import DeveloperAgent
from aios.agents.planner import PlannerAgent
from aios.cli.commands import COMMANDS, _error, _print_command_help, _print_help
from aios.config import ConfigEngine
from aios.context import ContextEngine
from aios.core import Kernel
from aios.events import EventsEngine
from aios.integrations.projdesk import (
    ProjDeskClient,
    ProjDeskError,
    ProjectAmbiguous,
    ProjectNotFound,
)
from aios.memory import MemoryEngine
from aios.runtime import RuntimeEngine
from aios.scheduler import KanbanEngine
from aios.security import SecurityEngine

VERSION_TEXT = f"AiosDeck v{__version__}"

_active_kernel: Kernel | None = None


def _handle_signal(signum: int, frame: object) -> None:  # noqa: ARG001
    print("\nShutting down...", file=sys.stderr)
    if _active_kernel is not None:
        _active_kernel.shutdown()
    sys.exit(0)


def main() -> None:
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
            _dispatch(COMMANDS["dashboard"], [], project_path)
        except (ProjectNotFound, ProjectAmbiguous, ProjDeskError) as exc:
            _error(str(exc))
        return

    cmd_name = args.command

    resolved = _find_command(cmd_name)
    if resolved is None:
        _error(f"Unknown command: {cmd_name}\nRun 'aios help' for available commands.")

    try:
        positional_args = [a for a in args.args if not a.startswith("-")]
        project_path = _resolve_project(positional_args)
        _dispatch(resolved, args.args, project_path)
    except (ProjectNotFound, ProjectAmbiguous, ProjDeskError) as exc:
        _error(str(exc))


def _find_command(cmd_name: str):
    if cmd_name in COMMANDS:
        return COMMANDS[cmd_name]

    for cmd in COMMANDS.values():
        if cmd_name in cmd.aliases:
            return cmd

    return None


def _resolve_project(args: list[str]) -> Path:
    candidate = args[0] if args else None
    if candidate is None:
        return Path.cwd()

    path = Path(candidate)
    if path.is_dir():
        return path.resolve()

    try:
        return ProjDeskClient().resolve(candidate)
    except ProjDeskError:
        return Path.cwd()


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


def _create_kernel(project_path: Path) -> Kernel:
    global _active_kernel  # noqa: PLW0603
    kernel = Kernel(project_path=str(project_path))
    kernel.register(ConfigEngine(project_path=project_path))
    kernel.register(ContextEngine(project_path=project_path))
    kernel.register(MemoryEngine(project_path=project_path))
    kernel.register(KanbanEngine(project_path=project_path))
    runtime = RuntimeEngine()
    kernel.register(runtime)
    kernel.register(DeveloperAgent(runtime))
    kernel.register(PlannerAgent(runtime))
    kernel.register(EventsEngine())
    kernel.register(SecurityEngine(project_path=project_path))
    _active_kernel = kernel
    return kernel
