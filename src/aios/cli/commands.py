"""Command Registry — single source of truth for the CLI surface.

Every command: the parser, help text, autocomplete, and eventual plugins —
all consume this registry. Adding a command means one entry, not changes
across five files.

Command implementations are organized by domain:
- cli/commands_exec.py — plan, research, review (execution commands)
- cli/commands_memory.py — memory add/list/forget/search
- <domain>/cli.py — each domain's own CLI commands
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from aios import __version__
from aios.cli.commands_exec import (
    cmd_plan as _cmd_plan,
)
from aios.cli.commands_exec import (
    cmd_research as _cmd_research,
)
from aios.cli.commands_exec import (
    cmd_review as _cmd_review,
)
from aios.cli.commands_memory import (
    cmd_memory_add,
    cmd_memory_forget,
    cmd_memory_list,
    cmd_memory_search,
)
from aios.core.console import (
    render_row,
    render_section,
)
from aios.knowledge.cli import (
    cmd_knowledge_index,
    cmd_knowledge_retrieve,
    cmd_knowledge_search,
    cmd_knowledge_sources,
)
from aios.learning.cli import _cmd_learning
from aios.quality.cli import cmd_quality_stats
from aios.routing.cli import _cmd_route
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
from aios.ui.cli import _cmd_ocean

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
# Core command implementations
# ---------------------------------------------------------------------------


def _cmd_dashboard(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    kernel = kernel_factory(project_path)
    kernel.start(render_dashboard=False)

    from aios.ui import (  # noqa: PLC0415
        PAGE_NAMES,
        ColorResolver,
        RenderContext,
        detect_color_mode,
        ocean_theme,
        overview_data,
        render_page,
        run_tui,
    )

    mode = detect_color_mode()
    resolver = ColorResolver(ocean_theme, mode)

    def _render(page_name: str) -> str:
        data = overview_data(kernel)
        return render_page(page_name, data, RenderContext(resolver=resolver))

    run_tui(_render, PAGE_NAMES)


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


def _cmd_init(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    aios_dir = project_path / ".aios"
    aios_dir.mkdir(parents=True, exist_ok=True)

    yaml_path = aios_dir / "project.yaml"
    if not yaml_path.exists():
        yaml_path.write_text(
            "# .aios/project.yaml — Project manifest for AiosDeck\n"
            "# ProjDesk prepares the development environment.\n"
            "# AiosDeck prepares the intelligence environment.\n"
            "\n"
            f"name: {project_path.name}\n"
            "runtime: opencode\n"
            "sandbox: ai-jail\n"
            "\n"
            "skills:\n"
            "  - project-dna\n"
            "  - coding-style\n"
        )

    GITIGNORE_RULES = [".aios/memory.db"]

    gitignore_path = project_path / ".gitignore"
    existing_text = gitignore_path.read_text() if gitignore_path.exists() else ""
    existing_lines = existing_text.splitlines()

    new_lines = [rule for rule in GITIGNORE_RULES if rule not in existing_lines]
    if new_lines:
        with gitignore_path.open("a") as f:
            if existing_text and not existing_text.endswith("\n"):
                f.write("\n")
            for rule in new_lines:
                f.write(f"{rule}\n")

    print(f"Project initialized at {aios_dir}")


def _cmd_help(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    _print_help()


def _cmd_complete(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    from aios.cli.completion import complete  # noqa: PLC0415

    suggestions = complete(raw_args)
    for s in suggestions:
        print(s)


def _cmd_exit(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    kernel = kernel_factory(project_path)
    kernel.shutdown()


# ---------------------------------------------------------------------------
# Help output helpers
# ---------------------------------------------------------------------------


def _print_help() -> None:
    print(f"{VERSION_TEXT}")
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
    print("  aios quality stats     Show quality gate telemetry")
    print("  aios policy show       Show security policy (capabilities/intents)")
    print("  aios security stats    Show security allow/deny audit trail")
    print("  aios knowledge <cmd>   Manage knowledge store (index/search/sources)")
    print("  aios skills <cmd>     Discover skills and view lifecycle stats")
    print("  aios learning <cmd>   Manage learning governance (candidates, approval)")
    print("  aios ocean [opts]     Open the ocean dashboard (interactive TUI)")
    print("  aios route <cmd>      Explain or inspect model routing decisions")
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
# Memory subcommands (registered inline, functions from commands_memory)
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
        execute=_cmd_dashboard,
    ),
    "doctor": Command(
        name="doctor",
        description="Run diagnostics",
        execute=_cmd_doctor,
    ),
    "init": Command(
        name="init",
        description="Initialize AiosDeck in the current project",
        execute=_cmd_init,
    ),
    "plan": Command(
        name="plan",
        description="Decompose goal into subtasks",
        execute=_cmd_plan,
    ),
    "research": Command(
        name="research",
        description="Research a question (repo/docs/web)",
        aliases=["r"],
        execute=_cmd_research,
    ),
    "review": Command(
        name="review",
        description="Review code, architecture, or conventions (read-only)",
        aliases=["rev"],
        execute=_cmd_review,
    ),
    "help": Command(
        name="help",
        description="Show help",
        execute=_cmd_help,
    ),
    "usage": Command(
        name="usage",
        description="Show token usage and cost telemetry",
        execute=cmd_usage,
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
        execute=_cmd_route,
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
        execute=_cmd_learning,
    ),
    "ocean": Command(
        name="ocean",
        description="Open the ocean dashboard (interactive TUI)",
        execute=_cmd_ocean,
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
