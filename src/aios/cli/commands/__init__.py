"""Command Registry — single source of truth for the CLI surface.

Every command: the parser, help text, autocomplete, and eventual plugins —
all consume this registry.

Command implementations are organized by domain:
- cli/commands/core.py — dashboard, doctor, init, help, exit, completion
- cli/commands/exec_cmds.py — plan, research, review
- cli/commands/memory.py — memory add/list/forget/search
- <domain>/cli.py — each domain's own CLI commands (knowledge, routing, ...)

Handlers are stored as ``"module.path:function"`` strings and resolved lazily
via ``importlib`` so that importing the registry (and running ``--help`` /
``--version``) never imports domain modules.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

from aios import __version__


@dataclass
class Command:
    name: str = ""
    description: str = ""
    aliases: list[str] = field(default_factory=list)
    subcommands: dict[str, Command] = field(default_factory=dict)
    handler: str | None = None
    hidden: bool = False

    @property
    def execute(self) -> Callable | None:
        if self.handler is None:
            return None
        module_path, _, attr = self.handler.partition(":")
        return getattr(importlib.import_module(module_path), attr)


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
    print("  aios benchmark <target> [opts]  Measure wall/CPU/memory (all|phases|validate|...)")
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
    handler="aios.cli.commands.memory:cmd_memory_add",
)

memory_forget = Command(
    name="forget",
    description="Remove project knowledge",
    aliases=["rm"],
    handler="aios.cli.commands.memory:cmd_memory_forget",
)

memory_list = Command(
    name="list",
    description="List project knowledge",
    aliases=["ls"],
    handler="aios.cli.commands.memory:cmd_memory_list",
)

memory_search = Command(
    name="search",
    description="Search project knowledge",
    aliases=["find"],
    handler="aios.cli.commands.memory:cmd_memory_search",
)

# ---------------------------------------------------------------------------
# Top-level commands
# ---------------------------------------------------------------------------

COMMANDS: dict[str, Command] = {
    "dashboard": Command(
        name="dashboard",
        description="Show dashboard",
        aliases=["start", "status"],
        handler="aios.cli.commands.core:cmd_dashboard",
    ),
    "doctor": Command(
        name="doctor",
        description="Run diagnostics",
        handler="aios.cli.commands.core:cmd_doctor",
    ),
    "init": Command(
        name="init",
        description="Initialize AiosDeck in the current project",
        handler="aios.cli.commands.core:cmd_init",
    ),
    "plan": Command(
        name="plan",
        description="Decompose goal into subtasks",
        handler="aios.cli.commands.exec_cmds:cmd_plan",
    ),
    "research": Command(
        name="research",
        description="Research a question (repo/docs/web)",
        aliases=["r"],
        handler="aios.cli.commands.exec_cmds:cmd_research",
    ),
    "review": Command(
        name="review",
        description="Review code, architecture, or conventions (read-only)",
        aliases=["rev"],
        handler="aios.cli.commands.exec_cmds:cmd_review",
    ),
    "help": Command(
        name="help",
        description="Show help",
        handler="aios.cli.commands.core:cmd_help",
    ),
    "completion": Command(
        name="completion",
        description="Print shell completion script (--bash | --zsh)",
        handler="aios.cli.commands.core:cmd_completion",
    ),
    "usage": Command(
        name="usage",
        description="Show token usage and cost telemetry",
        handler="aios.telemetry.cli:cmd_usage",
    ),
    "benchmark": Command(
        name="benchmark",
        description="Measure wall/CPU times for startup and commands",
        handler="aios.cli.commands.benchmark:cmd_benchmark",
    ),
    "quality": Command(
        name="quality",
        description="Query quality gate telemetry",
        subcommands={
            "stats": Command(
                name="stats",
                description="Show quality gate stats or records",
                aliases=["s"],
                handler="aios.quality.cli:cmd_quality_stats",
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
                handler="aios.security.cli:cmd_policy_show",
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
                handler="aios.security.cli:cmd_security_stats",
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
                handler="aios.knowledge.cli:cmd_knowledge_index",
            ),
            "search": Command(
                name="search",
                description="Search indexed knowledge",
                aliases=["s"],
                handler="aios.knowledge.cli:cmd_knowledge_search",
            ),
            "sources": Command(
                name="sources",
                description="List indexed knowledge sources",
                aliases=["ls"],
                handler="aios.knowledge.cli:cmd_knowledge_sources",
            ),
            "retrieve": Command(
                name="retrieve",
                description="Retrieve relevant knowledge with context selection",
                aliases=["get"],
                handler="aios.knowledge.cli:cmd_knowledge_retrieve",
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
        handler="aios.routing.cli:cmd_route",
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
                handler="aios.skills.cli:cmd_skills_discover",
            ),
            "inspect": Command(
                name="inspect",
                description="Show skill metadata and index status",
                handler="aios.skills.cli:cmd_skills_inspect",
            ),
            "stats": Command(
                name="stats",
                description="Show skill usage telemetry",
                handler="aios.skills.cli:cmd_skills_stats",
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
        handler="aios.learning.cli:cmd_learning",
    ),
    "ocean": Command(
        name="ocean",
        description="Open the ocean dashboard (interactive TUI)",
        handler="aios.ui.cli:cmd_ocean",
    ),
    "exit": Command(
        name="exit",
        description="Shut down gracefully",
        hidden=True,
        handler="aios.cli.commands.core:cmd_exit",
    ),
    "__complete": Command(
        name="__complete",
        description="Autocomplete hook",
        hidden=True,
        handler="aios.cli.commands.core:cmd_complete",
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
                handler="aios.backlog.cli:cmd_backlog_run",
            ),
            "list": Command(
                name="list",
                description="List pending tasks from a source",
                aliases=["ls"],
                handler="aios.backlog.cli:cmd_backlog_list",
            ),
            "add": Command(
                name="add",
                description="Add a task to the kanban backlog board",
                aliases=["a"],
                handler="aios.backlog.cli:cmd_backlog_add",
            ),
            "stats": Command(
                name="stats",
                description="Show backlog run telemetry",
                aliases=["s"],
                handler="aios.backlog.cli:cmd_backlog_stats",
            ),
        },
    ),
}
