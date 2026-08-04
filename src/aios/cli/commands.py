"""Command Registry — single source of truth for the CLI surface.

Every command: the parser, help text, autocomplete, and eventual plugins —
all consume this registry. Adding a command means one entry, not changes
across five files.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from aios import __version__
from aios.core.console import render_row, render_section
from aios.core.task import Task
from aios.memory.models import ProjectKnowledge

VERSION_TEXT = f"AiosDeck v{__version__}"


@dataclass
class Command:
    name: str = ""
    description: str = ""
    aliases: list[str] = field(default_factory=list)
    subcommands: dict[str, Command] = field(default_factory=dict)
    execute: Callable | None = None
    hidden: bool = False


def _error(msg: str) -> None:
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------


def _cmd_dashboard(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    kernel = kernel_factory(project_path)
    kernel.start()


def _cmd_doctor(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    as_json = "--json" in (raw_args or [])

    kernel = kernel_factory(project_path)
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


def _cmd_plan(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    intent = " ".join(raw_args) if raw_args else None
    if not intent:
        print("Usage: aios plan <intent>", file=sys.stderr)
        print("Example: aios plan 'add OAuth2 login'", file=sys.stderr)
        sys.exit(1)

    kernel = kernel_factory(project_path)
    kernel.start()

    planner = kernel.get_engine("planner")
    if planner is None:
        _error("Planner agent not available.")

    print("Planning...", file=sys.stderr)
    context = kernel.get_context()
    task = Task(description=intent, task_type="plan")
    result = planner.execute(task, context)

    if not result.success:
        msg = result.errors[0] if result.errors else "Planning failed."
        print(f"Error: {msg}", file=sys.stderr)
        sys.exit(1)

    print(result.output)


def _cmd_exit(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    kernel = kernel_factory(project_path)
    kernel.shutdown()


def _cmd_help(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    _print_help()


def _cmd_complete(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    from aios.cli.completion import complete  # noqa: PLC0415

    suggestions = complete(raw_args)
    for s in suggestions:
        print(s)


# ---------------------------------------------------------------------------
# Help output helpers
# ---------------------------------------------------------------------------


def _print_help() -> None:
    print(f"{VERSION_TEXT}")
    print("The AI Operating System for Developers.")
    print()
    print("Usage:")
    print("  aios                  Show dashboard")
    print("  aios doctor [--json]    Run diagnostics")
    print("  aios memory <cmd>     Manage project knowledge")
    print("  aios plan <intent>    Decompose goal into subtasks")
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
        if cmd.hidden:
            continue
        print(f"{prefix}{name:<20} {cmd.description}")
        if cmd.aliases:
            print(f"{prefix}  aliases: {', '.join(cmd.aliases)}")
        if cmd.subcommands:
            _print_command_list(cmd.subcommands, indent=indent + 2)


def _print_command_help(cmd: Command) -> None:
    print(f"{cmd.name} — {cmd.description}")
    if cmd.aliases:
        print(f"Aliases: {', '.join(cmd.aliases)}")
    if cmd.subcommands:
        print()
        print("Subcommands:")
        _print_command_list(cmd.subcommands, indent=2)


# ---------------------------------------------------------------------------
# Memory command implementations
# ---------------------------------------------------------------------------


def _cmd_list(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    kernel = kernel_factory(project_path)
    kernel.start()
    memory = kernel.get_engine("memory")
    if memory is None:
        print("Memory engine not available.")
        return

    knowledge: ProjectKnowledge = memory.recall()
    if knowledge.is_empty:
        print("No knowledge stored for this project.")
        return

    if knowledge.conventions:
        print("\nConventions:")
        for c in knowledge.conventions:
            print(f"  [{c.category}] {c.rule}")

    if knowledge.decisions:
        print("\nDecisions:")
        for d in knowledge.decisions:
            print(f"  {d.title}")
            if d.decision:
                print(f"    {d.decision}")

    if knowledge.patterns:
        print("\nPatterns:")
        for p in knowledge.patterns:
            print(f"  {p.name}")

    if knowledge.mistakes:
        print("\nMistakes to avoid:")
        for m in knowledge.mistakes:
            print(f"  [{m.severity}] {m.description}")


def _cmd_add(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    min_args = 2
    if len(raw_args) < min_args:
        print("Usage: aios memory add <convention|decision|pattern|mistake> <text>")
        return

    entry_type = raw_args[0]
    value = raw_args[1]

    if entry_type not in ("convention", "decision", "pattern", "mistake"):
        print(f"Unknown type: {entry_type}. Use convention, decision, pattern, or mistake.")
        return

    kernel = kernel_factory(project_path)
    kernel.start()
    memory = kernel.get_engine("memory")
    if memory is None:
        print("Memory engine not available.")
        return

    extra_idx = 2
    if entry_type == "convention":
        category = raw_args[extra_idx] if len(raw_args) > extra_idx else ""
        memory.remember_convention(rule=value, category=category)
    elif entry_type == "decision":
        memory.remember_decision(title=value)
    elif entry_type == "pattern":
        memory.remember_pattern(name=value)
    elif entry_type == "mistake":
        severity = raw_args[extra_idx] if len(raw_args) > extra_idx else "warning"
        memory.remember_mistake(description=value, severity=severity)

    print(f"{entry_type.capitalize()} saved: {value}")


def _cmd_forget(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    min_args = 2
    if len(raw_args) < min_args:
        print("Usage: aios memory forget <convention|decision|pattern|mistake> <text>")
        return

    entry_type = raw_args[0]
    value = raw_args[1]

    if entry_type not in ("convention", "decision", "pattern", "mistake"):
        print(f"Unknown type: {entry_type}. Use convention, decision, pattern, or mistake.")
        return

    kernel = kernel_factory(project_path)
    kernel.start()
    memory = kernel.get_engine("memory")
    if memory is None:
        print("Memory engine not available.")
        return

    store = getattr(memory, "_store", None)
    if store is None:
        print("Memory store not available.")
        return

    delete_map = {
        "convention": store.delete_convention,
        "decision": store.delete_decision,
        "pattern": store.delete_pattern,
        "mistake": store.delete_mistake,
    }

    deleted = delete_map[entry_type](value)
    if deleted:
        print(f"Removed: {value}")
    else:
        print(f"Not found: {value}")


def _cmd_search(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    if not raw_args:
        print("Usage: aios memory search <query>")
        return

    query = raw_args[0]
    kernel = kernel_factory(project_path)
    kernel.start()
    memory = kernel.get_engine("memory")
    if memory is None:
        print("Memory engine not available.")
        return

    store = getattr(memory, "_store", None)
    if store is None:
        print("Memory store not available.")
        return

    results = store.search(query)
    if not results:
        print(f"No results for: {query}")
        return

    for kind, text in results:
        print(f"  [{kind}] {text}")


# ---------------------------------------------------------------------------
# Memory subcommands
# ---------------------------------------------------------------------------

memory_add = Command(
    name="add",
    description="Add project knowledge",
    aliases=["a"],
    subcommands={
        "convention": Command(name="convention", description="Add a coding convention"),
        "decision": Command(name="decision", description="Record an architecture decision"),
        "pattern": Command(name="pattern", description="Add a design pattern"),
        "mistake": Command(name="mistake", description="Record a mistake to avoid"),
    },
    execute=_cmd_add,
)

memory_forget = Command(
    name="forget",
    description="Remove project knowledge",
    aliases=["rm"],
    execute=_cmd_forget,
)

memory_list = Command(
    name="list",
    description="List project knowledge",
    aliases=["ls"],
    execute=_cmd_list,
)

memory_search = Command(
    name="search",
    description="Search project knowledge",
    aliases=["find"],
    execute=_cmd_search,
)

# ---------------------------------------------------------------------------
# Top-level commands
# ---------------------------------------------------------------------------

COMMANDS: dict[str, Command] = {
    "dashboard": Command(
        name="dashboard",
        description="Show dashboard",
        aliases=["start", "status"],
        execute=_cmd_dashboard,
    ),
    "doctor": Command(
        name="doctor",
        description="Run diagnostics",
        execute=_cmd_doctor,
    ),
    "plan": Command(
        name="plan",
        description="Decompose goal into subtasks",
        execute=_cmd_plan,
    ),
    "help": Command(
        name="help",
        description="Show help",
        execute=_cmd_help,
    ),
    "exit": Command(
        name="exit",
        description="Shut down gracefully",
        hidden=True,
        execute=_cmd_exit,
    ),
    "__complete": Command(
        name="__complete",
        description="Autocomplete hook",
        hidden=True,
        execute=_cmd_complete,
    ),
    "memory": Command(
        name="memory",
        description="Manage project knowledge",
        aliases=["mem"],
        subcommands={
            "add": memory_add,
            "forget": memory_forget,
            "list": memory_list,
            "search": memory_search,
        },
    ),
}
