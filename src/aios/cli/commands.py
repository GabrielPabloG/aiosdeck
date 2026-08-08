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
from aios.core.run_result import RunResult, StageSummary
from aios.core.task import Task
from aios.memory.models import ProjectKnowledge
from aios.research import ResearchTask
from aios.research.schema import research_result_to_json

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


_RESEARCH_SCOPES = ("repo", "docs", "web", "mixed")


def _cmd_research(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    opts: dict = {"scope": "mixed", "json": False, "output": None}
    positional: list[str] = []
    i = 0
    while i < len(raw_args or []):
        arg = raw_args[i]
        if arg == "--json":
            opts["json"] = True
        elif arg == "--scope":
            i += 1
            value = raw_args[i] if i < len(raw_args) else ""
            if value not in _RESEARCH_SCOPES:
                _error(f"--scope must be one of {', '.join(_RESEARCH_SCOPES)}")
            opts["scope"] = value
        elif arg == "--output":
            i += 1
            value = raw_args[i] if i < len(raw_args) else ""
            if not value:
                _error("--output requires a file path")
            opts["output"] = value
        elif arg.startswith("-"):
            _error(f"unknown option {arg}")
        else:
            positional.append(arg)
        i += 1

    question = " ".join(positional).strip()
    if not question:
        print(
            "Usage: aios research <question> "
            "[--scope repo|docs|web|mixed] [--json] [--output FILE]",
            file=sys.stderr,
        )
        sys.exit(1)

    kernel = kernel_factory(project_path)
    kernel.start()

    researcher = kernel.get_engine("research")
    if researcher is None:
        _error("Research agent not available.")

    context = kernel.get_context()
    task = ResearchTask(
        question=question,
        scope=opts["scope"],
        context_packet=context.to_dict() if context else {},
    )

    with ProgressSpinner("Researching"):
        result = researcher.research(task)

    if opts["output"]:
        with Path(opts["output"]).open("w", encoding="utf-8") as f:
            f.write(research_result_to_json(result) + "\n")
        print(f"Wrote research report: {opts['output']}")
        return
    if opts["json"]:
        print(research_result_to_json(result))
        return

    _print_research_text(result)


def _print_research_text(result) -> None:
    print(f"status: {result.status}")
    print(f"summary: {result.summary_short}")
    print(f"confidence: {result.confidence_overall:.2f}")
    if result.error:
        print(f"error: {result.error}")

    if result.findings:
        print("\nFindings:")
        for f in result.findings:
            confidence = f"{f.confidence:.2f}"
            print(f"  - [{f.id}] (conf {confidence}) {f.claim}")
    elif result.sources:
        print("\nNo findings synthesized.")

    if result.sources:
        print("\nSources:")
        for s in result.sources:
            print(f"  - {s.type}: {s.title} ({s.url})")

    if result.recommendations:
        print("\nRecommendations:")
        for r in result.recommendations:
            print(f"  - [{r.priority}] {r.action}")

    if result.memory_candidates:
        print("\nMemory candidates (advisory, not persisted):")
        for m in result.memory_candidates:
            print(f"  - [{m.kind}] {m.content}")


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

    context = kernel.get_context()
    task = Task(description=intent, task_type="plan")
    mode = "plan-run" if run_mode else "plan"

    with ProgressSpinner("Running workflow" if run_mode else "Planning"):
        result = kernel.run(
            task,
            context,
            mode=mode,
            on_stage=_render_stage if run_mode else None,
        )

    _render_run_result(result)

    if not result.success:
        for err in result.errors:
            print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)


def _render_plan_list(plan: dict) -> None:
    subtasks = plan.get("subtasks", [])
    if not subtasks:
        print("No subtasks to execute.")
        return
    log_step("📋", f"Plano de Execução ({len(subtasks)} tarefas):")
    for st in subtasks:
        log_step("", f"  • {st['description']}")


def _render_stage(stage: StageSummary) -> None:
    """Render a pipeline stage as it completes (real-time progress)."""
    if stage.name == "planner":
        plan = (stage.details or {}).get("plan")
        if stage.status == "success" and plan:
            _render_plan_list(plan)
        return
    if stage.name.startswith("developer:"):
        description = (stage.details or {}).get("description", stage.name)
        mark = "✓" if stage.status == "success" else "✗"
        print(f"  [{mark}] {description}")


def _render_run_result(result: RunResult) -> None:
    """Render the final summary from the standardized RunResult."""
    if result.subtask_count:
        print(f"\n{result.completed_count}/{result.subtask_count} tasks completed")
    elif result.output:
        print(result.output)


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
    print("  aios research <q>     Research a question (repo/docs/web)")
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
