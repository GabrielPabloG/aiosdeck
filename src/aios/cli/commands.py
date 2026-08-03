"""Command Registry — single source of truth for the CLI surface.

Every command: the parser, help text, autocomplete, and eventual plugins —
all consume this registry. Adding a command means one entry, not changes
across five files.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from aios.memory.models import ProjectKnowledge


@dataclass
class Command:
    name: str = ""
    description: str = ""
    aliases: list[str] = field(default_factory=list)
    subcommands: dict[str, Command] = field(default_factory=dict)
    execute: Callable | None = None


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


# --- Memory subcommands ---

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

# --- Top-level commands ---

COMMANDS: dict[str, Command] = {
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
