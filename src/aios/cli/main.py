"""CLI entry point for the aios command."""

import argparse
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from aios import __version__
from aios.cli.commands import COMMANDS, _error, _print_command_help, _print_help

if TYPE_CHECKING:
    from aios.core import Kernel

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
        from aios.integrations.projdesk.exceptions import ProjDeskError  # noqa: PLC0415

        try:
            project_path = _resolve_project([])
            _dispatch(COMMANDS["dashboard"], [], project_path)
        except ProjDeskError as exc:
            _error(str(exc))
        return

    cmd_name = args.command

    resolved = _find_command(cmd_name)
    if resolved is None:
        _error(f"Unknown command: {cmd_name}\nRun 'aios help' for available commands.")

    from aios.integrations.projdesk.exceptions import ProjDeskError  # noqa: PLC0415

    try:
        positional_args = [a for a in args.args if not a.startswith("-")]
        project_path = _resolve_project(positional_args)
        _dispatch(resolved, args.args, project_path)
    except ProjDeskError as exc:
        _error(str(exc))


def _find_command(cmd_name: str):
    if cmd_name in COMMANDS:
        return COMMANDS[cmd_name]

    for cmd in COMMANDS.values():
        if cmd_name in cmd.aliases:
            return cmd

    return None


def _resolve_project(args: list[str]) -> Path:
    from aios.integrations.projdesk import (  # noqa: PLC0415
        ProjDeskClient,
        ProjDeskError,
    )

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
    if not raw_args and cmd.handler is not None:
        cmd.execute(raw_args, project_path, _kernel_factory)
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
        if sub.subcommands or sub.handler is not None:
            _dispatch(sub, remaining, project_path)
        elif cmd.handler is not None:
            cmd.execute(raw_args, project_path, _kernel_factory)
        else:
            _print_command_help(sub)
        return

    if cmd.handler is not None:
        cmd.execute(raw_args, project_path, _kernel_factory)
        return

    _error(f"Unknown subcommand: {sub_name}")


def _kernel_factory(project_path: Path) -> Kernel:
    from aios.core.factory import create_kernel  # noqa: PLC0415

    global _active_kernel  # noqa: PLW0603
    kernel = create_kernel(project_path)
    _active_kernel = kernel
    return kernel
