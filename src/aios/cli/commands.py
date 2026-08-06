"""Command Registry — single source of truth for the CLI surface.

Every command: the parser, help text, autocomplete, and eventual plugins —
all consume this registry. Adding a command means one entry, not changes
across five files.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from aios import __version__
from aios.core.console import (
    ProgressSpinner,
    log_step,
    render_row,
    render_section,
)
from aios.core.task import Task
from aios.memory.models import ProjectKnowledge
from aios.scheduler.backlog_writer import write_backlog

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


_REVIEW_LEVELS = ("architecture", "conventions", "security")
_REVIEW_OUTPUTS = ("text", "json", "file")


def _parse_review_args(raw_args: list[str]) -> dict:
    opts: dict = {
        "level": "conventions",
        "output": "text",
        "dry_run": False,
        "diff_only": False,
        "target": None,
    }
    i = 0
    while i < len(raw_args):
        arg = raw_args[i]
        if arg == "--dry-run":
            opts["dry_run"] = True
        elif arg == "--diff":
            opts["diff_only"] = True
        elif arg in ("--level", "--output"):
            i += 1
            value = raw_args[i] if i < len(raw_args) else ""
            choices = _REVIEW_LEVELS if arg == "--level" else _REVIEW_OUTPUTS
            if value not in choices:
                _error(f"{arg} must be one of {', '.join(choices)}")
            opts["level" if arg == "--level" else "output"] = value
        elif arg.startswith("-"):
            _error(f"unknown option {arg}")
        elif opts["target"] is None:
            opts["target"] = arg
        i += 1
    return opts


def _print_review_text(report: dict) -> None:
    print(report["summary"])
    for item in report.get("items", [])[:20]:
        line = item.get("line", "?")
        print(f"{item['severity'].upper()}: {item['file']}:{line} {item['message']}")


def _cmd_review(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    opts = _parse_review_args(raw_args or [])
    target = opts["target"] or str(Path.cwd())

    kernel = kernel_factory(project_path)
    kernel.start()

    reviewer = kernel.get_engine("reviewer")
    if reviewer is None:
        _error("Reviewer agent not available.")

    if opts["diff_only"]:
        target = _resolve_diff_target(target)

    with ProgressSpinner("Reviewing"):
        report = reviewer.review(target, level=opts["level"])

    if opts["dry_run"]:
        report["summary"] = f"{report['summary']} (dry-run, read-only)"
        print(json.dumps(report, indent=2))
        return
    if opts["output"] == "json":
        print(json.dumps(report, indent=2))
        return
    if opts["output"] == "file":
        with Path("reviewer_report.json").open("w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print("Wrote report: reviewer_report.json")
        return
    _print_review_text(report)


def _resolve_diff_target(target: str) -> str:
    result = subprocess.run(
        ["git", "diff", "HEAD", "--name-only"],
        capture_output=True,
        text=True,
        check=False,
        cwd=target,
    )
    names = [line for line in result.stdout.splitlines() if line]
    if not names:
        return target
    diff_dir = Path(tempfile.mkdtemp(prefix="aios-review-diff-"))
    for name in names:
        source = Path(target) / name
        if source.is_file():
            dest = diff_dir / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(source.read_text(encoding="utf-8", errors="replace"))
    return str(diff_dir)


def _cmd_plan(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    run_mode = "--run" in (raw_args or [])

    clean_args = [a for a in (raw_args or []) if a != "--run"]
    intent = " ".join(clean_args) if clean_args else None
    if not intent:
        print("Usage: aios plan <intent>", file=sys.stderr)
        print("Example: aios plan 'add OAuth2 login'", file=sys.stderr)
        sys.exit(1)

    kernel = kernel_factory(project_path)
    kernel.start()

    planner = kernel.get_engine("planner")
    if planner is None:
        _error("Planner agent not available.")

    context = kernel.get_context()
    task = Task(description=intent, task_type="plan")

    with ProgressSpinner("Planning"):
        result = planner.execute(task, context)

    if not result.success:
        msg = result.errors[0] if result.errors else "Planning failed."
        print(f"Error: {msg}", file=sys.stderr)
        sys.exit(1)

    if not run_mode:
        print(result.output)
        return

    plan = json.loads(result.output)
    _execute_subtasks(plan, intent, kernel, context)


def _wire_event_bus(kernel) -> None:
    events = kernel.get_engine("events")
    scheduler = kernel.get_engine("scheduler")
    if scheduler is not None and events is not None and getattr(events, "bus", None) is not None:
        scheduler.set_event_bus(events.bus)


def _execute_subtasks(plan: dict, intent: str, kernel, context) -> None:
    subtasks = plan.get("subtasks", [])
    if not subtasks:
        print("No subtasks to execute.")
        return

    developer = kernel.get_engine("developer")
    if developer is None:
        _error("Developer agent not available.")

    scheduler = kernel.get_engine("scheduler")
    _wire_event_bus(kernel)

    log_step("📋", f"Plano de Execução ({len(subtasks)} tarefas):")
    for st in subtasks:
        log_step("", f"  • {st['description']}")

    board = None
    cards: list = []
    tasks_list: list[dict] = [{"title": st["description"], "checked": False} for st in subtasks]
    if scheduler is not None:
        board = scheduler.create_board(f"Sprint: {intent[:40]}")
        for st in subtasks:
            cards.append(scheduler.create_card(board_id=board.id, title=st["description"]))
        write_backlog(tasks_list, active_index=1)

    total = len(subtasks)
    completed = 0

    for idx, st in enumerate(subtasks):
        card = cards[idx] if idx < len(cards) else None
        red_subtask = None
        if card is not None:
            scheduler.move_card(card.id, "Todo")
            red_subtask = scheduler.create_subtask(
                card_id=card.id,
                description="failing test (RED)",
            )
            scheduler.move_card(card.id, "InProgress")

        dev_task = Task(description=st["description"], task_type="code")
        with ProgressSpinner(st["description"]):
            dev_result = developer.execute(dev_task, context)

        if dev_result.success:
            if card is not None and red_subtask is not None:
                scheduler.complete_subtask(red_subtask.id)
                scheduler.move_card(card.id, "Review")
                scheduler.pass_tdd_gate(card.id)
                scheduler.move_card(card.id, "Done")
            tasks_list[idx]["checked"] = True
            next_active = idx + 2 if idx + 2 <= total else None
            write_backlog(tasks_list, active_index=next_active)
            print(f"  [✓] {st['description']}")
            completed += 1
        else:
            if card is not None:
                scheduler.block_card(
                    card.id,
                    reason="TDD gate failed: execution did not pass",
                )
            write_backlog(tasks_list, active_index=idx + 1)
            print(f"  [✗] {st['description']}")
            break

    print(f"\n{completed}/{total} tasks completed")

    if board is not None and scheduler is not None:
        write_backlog(tasks_list, active_index=None)


def _cmd_exit(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    kernel = kernel_factory(project_path)
    kernel.shutdown()


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
