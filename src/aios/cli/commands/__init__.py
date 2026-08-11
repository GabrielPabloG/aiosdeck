"""Command Registry — single source of truth for the CLI surface.

Every command: the parser, help text, autocomplete, and eventual plugins —
all consume this registry.

Command implementations are organized by domain:
- cli/commands/core.py — dashboard, doctor, init, help, exit, completion
- cli/commands/exec_cmds.py — plan, research, review
- cli/commands/memory.py — memory add/list/forget/search
- <domain>/cli.py — each domain's own CLI commands (knowledge, routing, ...)
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field

from aios import __version__
from aios.backlog.cli import (
    cmd_backlog_add,
    cmd_backlog_list,
    cmd_backlog_run,
    cmd_backlog_stats,
)
from aios.cli.commands.benchmark import cmd_benchmark
from aios.cli.commands.core import (
    cmd_complete,
    cmd_completion,
    cmd_dashboard,
    cmd_doctor,
    cmd_exit,
    cmd_help,
    cmd_init,
)
from aios.cli.commands.exec_cmds import (
    _gate_label as _gate_label,
)
from aios.cli.commands.exec_cmds import (
    _gates_json as _gates_json,
)
from aios.cli.commands.exec_cmds import (
    _render_gate_trail as _render_gate_trail,
)
from aios.cli.commands.exec_cmds import (
    _render_plan_list as _render_plan_list,
)
from aios.cli.commands.exec_cmds import (
    _render_run_result as _render_run_result,
)
from aios.cli.commands.exec_cmds import (
    _render_stage as _render_stage,
)
from aios.cli.commands.exec_cmds import (
    _run_result_to_json as _run_result_to_json,
)
from aios.cli.commands.exec_cmds import (
    cmd_plan,
    cmd_research,
    cmd_review,
)
from aios.cli.commands.memory import (
    cmd_memory_add,
    cmd_memory_forget,
    cmd_memory_list,
    cmd_memory_search,
)
from aios.knowledge.cli import (
    cmd_knowledge_index,
    cmd_knowledge_retrieve,
    cmd_knowledge_search,
    cmd_knowledge_sources,
)
from aios.learning.cli import cmd_learning  # noqa: E402
from aios.quality.cli import cmd_quality_stats
from aios.routing.cli import cmd_route
from aios.security.cli import (
    cmd_policy_show,
    cmd_security_stats,
)
from aios.skills.cli import (
    cmd_skills_discover,
    cmd_skills_inspect,
    cmd_skills_stats,
)
from aios.telemetry.cli import cmd_usage
from aios.ui.cli import cmd_ocean


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


def _print_help() -> None:
    """Print the full help text (used directly by main.py dispatch)."""
    print(f"AiosDeck v{__version__}")
    print("The AI Operating System for Developers.")
    print()
    print("Usage:")
    print("  aios                  Show dashboard")
    print("  aios init               Initialize AiosDeck project")
    print("  aios doctor [--json]    Run diagnostics")
    print("  aios memory <cmd>     Manage project knowledge")
    print("  aios plan <intent>    Decompose goal into subtasks")
    print("  aios review [target]  Review code/architecture/conventions (read-only)")
    print("  aios research <q>     Research a question (repo/docs/web)")
    print("  aios usage [opts]     Show token usage and cost telemetry")
    print("  aios benchmark <target> [opts]  Measure wall/CPU times (all|phases|startup|...)")
    print("  aios quality stats     Show quality gate telemetry")
    print("  aios policy show       Show security policy (capabilities/intents)")
    print("  aios security stats    Show security allow/deny audit trail")
    print("  aios knowledge <cmd>   Manage knowledge store (index/search/sources)")
    print("  aios skills <cmd>     Discover skills and view lifecycle stats")
    print("  aios learning <cmd>   Manage learning governance (candidates, approval)")
    print("  aios ocean [opts]     Open the ocean dashboard (interactive TUI)")
    print("  aios route <cmd>      Explain or inspect model routing decisions")
    print("  aios backlog <cmd>    Run, list, add, or inspect backlog tasks")
    print("  aios help             Show this help")
    print("  aios completion [sh]  Print a shell completion script (--bash|--zsh)")
    print()
    print("Commands:")
    _print_command_list(COMMANDS, indent=2)
    print()
    print("Aliases:")
    print("  start, status         Show dashboard")
    print("  exit                  Shut down gracefully")
    print()
    print("Project: https://github.com/GabrielPabloG/aiosdeck")


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
    execute=cmd_memory_add,
)

memory_forget = Command(
    name="forget",
    description="Remove project knowledge",
    aliases=["rm"],
    execute=cmd_memory_forget,
)

memory_list = Command(
    name="list",
    description="List project knowledge",
    aliases=["ls"],
    execute=cmd_memory_list,
)

memory_search = Command(
    name="search",
    description="Search project knowledge",
    aliases=["find"],
    execute=cmd_memory_search,
)

# ---------------------------------------------------------------------------
# Top-level commands
# ---------------------------------------------------------------------------

COMMANDS: dict[str, Command] = {
    "dashboard": Command(
        name="dashboard",
        description="Show dashboard",
        aliases=["start", "status"],
        execute=cmd_dashboard,
    ),
    "doctor": Command(
        name="doctor",
        description="Run diagnostics",
        execute=cmd_doctor,
    ),
    "init": Command(
        name="init",
        description="Initialize AiosDeck in the current project",
        execute=cmd_init,
    ),
    "plan": Command(
        name="plan",
        description="Decompose goal into subtasks",
        execute=cmd_plan,
    ),
    "research": Command(
        name="research",
        description="Research a question (repo/docs/web)",
        aliases=["r"],
        execute=cmd_research,
    ),
    "review": Command(
        name="review",
        description="Review code, architecture, or conventions (read-only)",
        aliases=["rev"],
        execute=cmd_review,
    ),
    "help": Command(
        name="help",
        description="Show help",
        execute=cmd_help,
    ),
    "completion": Command(
        name="completion",
        description="Print shell completion script (--bash | --zsh)",
        execute=cmd_completion,
    ),
    "usage": Command(
        name="usage",
        description="Show token usage and cost telemetry",
        execute=cmd_usage,
    ),
    "benchmark": Command(
        name="benchmark",
        description="Measure wall/CPU times for startup and commands",
        execute=cmd_benchmark,
    ),
    "quality": Command(
        name="quality",
        description="Query quality gate telemetry",
        subcommands={
            "stats": Command(
                name="stats",
                description="Show quality gate stats or records",
                aliases=["s"],
                execute=cmd_quality_stats,
            ),
        },
    ),
    "policy": Command(
        name="policy",
        description="Show the security policy (capabilities, intents, expansion)",
        subcommands={
            "show": Command(
                name="show",
                description="Show canonical capabilities, default intents, and expansion",
                aliases=["s"],
                execute=cmd_policy_show,
            ),
        },
    ),
    "security": Command(
        name="security",
        description="Query the security audit trail",
        subcommands={
            "stats": Command(
                name="stats",
                description="Show security allow/deny decisions",
                aliases=["s"],
                execute=cmd_security_stats,
            ),
        },
    ),
    "knowledge": Command(
        name="knowledge",
        description="Manage knowledge store",
        aliases=["k"],
        subcommands={
            "index": Command(
                name="index",
                description="Index project knowledge sources",
                aliases=["i"],
                execute=cmd_knowledge_index,
            ),
            "search": Command(
                name="search",
                description="Search indexed knowledge",
                aliases=["s"],
                execute=cmd_knowledge_search,
            ),
            "sources": Command(
                name="sources",
                description="List indexed knowledge sources",
                aliases=["ls"],
                execute=cmd_knowledge_sources,
            ),
            "retrieve": Command(
                name="retrieve",
                description="Retrieve relevant knowledge with context selection",
                aliases=["get"],
                execute=cmd_knowledge_retrieve,
            ),
        },
    ),
    "route": Command(
        name="route",
        description="Explain and inspect model routing decisions",
        aliases=["rt"],
        subcommands={
            "explain": Command(
                name="explain",
                description="Explain which model would be chosen for a given input",
                aliases=["e"],
            ),
            "stats": Command(
                name="stats",
                description="Show routing telemetry stats, records, or accuracy",
                aliases=["s"],
            ),
        },
        execute=cmd_route,
    ),
    "skills": Command(
        name="skills",
        description="Discover and inspect intelligent skills",
        aliases=["sk"],
        subcommands={
            "discover": Command(
                name="discover",
                description="Discover skills relevant to an intent",
                aliases=["d"],
                execute=cmd_skills_discover,
            ),
            "inspect": Command(
                name="inspect",
                description="Show skill metadata and index status",
                execute=cmd_skills_inspect,
            ),
            "stats": Command(
                name="stats",
                description="Show skill usage telemetry",
                execute=cmd_skills_stats,
            ),
        },
    ),
    "learning": Command(
        name="learning",
        description="Manage learning governance — candidates, approval, ingestion",
        aliases=["learn"],
        subcommands={
            "candidates": Command(
                name="candidates",
                description="List learning candidates",
                aliases=["ls"],
            ),
            "approve": Command(
                name="approve",
                description="Approve a learning candidate",
            ),
            "reject": Command(
                name="reject",
                description="Reject a learning candidate (--reason required)",
            ),
            "ingest": Command(
                name="ingest",
                description="Ingest an approved candidate into memory",
            ),
            "export": Command(
                name="export",
                description="Export approved/ingested candidates to file",
            ),
        },
        execute=cmd_learning,
    ),
    "ocean": Command(
        name="ocean",
        description="Open the ocean dashboard (interactive TUI)",
        execute=cmd_ocean,
    ),
    "exit": Command(
        name="exit",
        description="Shut down gracefully",
        hidden=True,
        execute=cmd_exit,
    ),
    "__complete": Command(
        name="__complete",
        description="Autocomplete hook",
        hidden=True,
        execute=cmd_complete,
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
    "backlog": Command(
        name="backlog",
        description="Run, list, add, or inspect backlog tasks",
        aliases=["bl"],
        subcommands={
            "run": Command(
                name="run",
                description="Execute backlog tasks sequentially",
                aliases=["r"],
                execute=cmd_backlog_run,
            ),
            "list": Command(
                name="list",
                description="List pending tasks from a source",
                aliases=["ls"],
                execute=cmd_backlog_list,
            ),
            "add": Command(
                name="add",
                description="Add a task to the kanban backlog board",
                aliases=["a"],
                execute=cmd_backlog_add,
            ),
            "stats": Command(
                name="stats",
                description="Show backlog run telemetry",
                aliases=["s"],
                execute=cmd_backlog_stats,
            ),
        },
    ),
}
