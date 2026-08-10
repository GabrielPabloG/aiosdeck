"""CLI commands for backlog operations."""

import json
import sys
from collections.abc import Callable
from pathlib import Path

from aios.backlog.parser import load_tasks_from_file, load_tasks_from_kanban
from aios.backlog.runner import BacklogRunner


def _resolve_kernel(kernel_factory, project_path):
    kernel = kernel_factory(project_path)
    kernel.start()
    return kernel


def cmd_backlog_run(  # noqa: PLR0912, PLR0915
    raw_args: list[str],
    project_path: Path,
    kernel_factory: Callable,
) -> None:
    stop_on_error = True
    from_index = 0
    source: str | None = None
    create_branch = False

    i = 0
    while i < len(raw_args or []):
        arg = raw_args[i]
        if arg == "--continue":
            stop_on_error = False
        elif arg == "--from":
            i += 1
            from_index = int(raw_args[i]) if i < len(raw_args) else 0
        elif arg == "--branch":
            create_branch = True
        elif arg == "--no-branch":
            create_branch = False
        elif arg.startswith("--source=") or (arg.startswith("--") and "=" in arg):
            source = arg.split("=", 1)[1]
        elif arg.startswith("board:") or arg.startswith("file:"):
            source = arg
        i += 1

    if source is None:
        print("Usage: aios backlog run --source=board:NAME | --source=file:PATH")
        print("  [--branch] [--no-branch] [--continue] [--from N]")
        sys.exit(1)

    kernel = _resolve_kernel(kernel_factory, project_path)
    kanban = kernel.get_engine("scheduler")
    telemetry = kernel.get_engine("telemetry")

    if source.startswith("board:"):
        board_name = source.split(":", 1)[1]
        tasks = load_tasks_from_kanban(kanban, board_name)
    elif source.startswith("file:"):
        file_path = source.split(":", 1)[1]
        tasks = load_tasks_from_file(project_path / file_path)
    else:
        tasks = []

    if not tasks:
        print("No tasks found in source.")
        sys.exit(0)

    runner = BacklogRunner(kernel, kanban=kanban, telemetry=telemetry)
    print(f"Running {len(tasks)} task(s) from {source} (from index {from_index})...")

    results = runner.run(
        tasks,
        stop_on_error=stop_on_error,
        from_index=from_index,
        create_branch=create_branch,
    )

    succeeded = sum(1 for r in results if r.status == "succeeded")
    failed = sum(1 for r in results if r.status == "failed")
    skipped = sum(1 for r in results if r.status == "skipped")

    print(f"\nDone: {succeeded} succeeded, {failed} failed, {skipped} skipped")
    if failed:
        for r in results:
            if r.status == "failed":
                print(f"  FAIL: {r.task.title} — {r.error}", file=sys.stderr)
        sys.exit(1)


def cmd_backlog_list(
    raw_args: list[str],
    project_path: Path,
    kernel_factory: Callable,
) -> None:
    source: str | None = None
    for arg in raw_args or []:
        if arg.startswith("board:") or arg.startswith("--source=board:"):
            source = arg.split(":", 1)[1] if "=" not in arg else arg.split("=", 1)[1]
            if ":" in source:
                source = source.split(":", 1)[1] if "=" in arg else source
        elif arg.startswith("file:") or arg.startswith("--source=file:"):
            file_path = arg.split(":", 1)[1] if "=" not in arg else arg.split("=", 1)[1]
            if ":" in file_path:
                file_path = file_path.split(":", 1)[1] if "=" in arg else file_path
            tasks = load_tasks_from_file(project_path / file_path)
            for t in tasks:
                print(f"  [{t.index}] {t.type}({t.scope}): {t.subject} {t.version}")
            return
        if source:
            break

    if not source:
        print("Usage: aios backlog list board:NAME")
        sys.exit(1)

    kernel = _resolve_kernel(kernel_factory, project_path)
    kanban = kernel.get_engine("scheduler")
    tasks = load_tasks_from_kanban(kanban, source)

    for t in tasks:
        print(f"  [{t.index}] {t.type}({t.scope}): {t.subject} {t.version}")


def cmd_backlog_add(
    raw_args: list[str],
    project_path: Path,
    kernel_factory: Callable,
) -> None:
    if not raw_args:
        print("Usage: aios backlog add <title> [--board NAME]")
        sys.exit(1)

    title = raw_args[0]
    board_name = "backlog"
    if len(raw_args) > 1 and raw_args[1] == "--board":
        board_name = raw_args[2] if len(raw_args) > 2 else "backlog"  # noqa: PLR2004

    kernel = _resolve_kernel(kernel_factory, project_path)
    kanban = kernel.get_engine("scheduler")

    boards = kanban.list_boards()
    board = None
    for b in boards:
        if b.name == board_name:
            board = b
            break
    if board is None:
        board = kanban.create_board(board_name)

    card = kanban.create_card(board.id, title)
    print(f"Card #{card.id} created on board '{board_name}': {title}")


def cmd_backlog_stats(
    raw_args: list[str],
    project_path: Path,
    kernel_factory: Callable,
) -> None:
    as_json = "--json" in (raw_args or [])

    kernel = _resolve_kernel(kernel_factory, project_path)
    telemetry = kernel.get_engine("telemetry")

    stats = telemetry.query_backlog_stats()

    if as_json:
        print(json.dumps(stats, indent=2, default=str))
        return

    if not stats:
        print("No backlog runs recorded.")
        return

    succeeded = sum(1 for s in stats if s["status"] == "succeeded")
    failed = sum(1 for s in stats if s["status"] == "failed")

    print(f"Total: {len(stats)} run(s) — {succeeded} succeeded, {failed} failed")
    for s in stats[:10]:
        dur = s.get("duration_ms", 0) or 0
        print(f"  {s['status']:>10}  {dur:8.0f}ms  {s['task_title'][:60]}")
