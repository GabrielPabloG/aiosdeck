"""Backlog writer — produces TODO.md as the canonical textual backlog."""

import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def write_backlog(
    tasks: Sequence[dict[str, Any]],
    active_index: int | None = None,
    output_path: Path | str = "TODO.md",
) -> Path:
    """Write the textual backlog to a file atomically.

    Args:
        tasks: Sequence of dicts with ``title`` (str) and ``checked`` (bool) keys.
        active_index: 1-based index of the active task (rendered with spinner prefix).
        output_path: Path to write the TODO.md file.

    Returns:
        Path to the written file.
    """
    output_path = Path(output_path)
    lines: list[str] = []
    total = len(tasks)

    if total:
        lines.append(f"# Backlog ({total})")
        lines.append("")

    for i, task in enumerate(tasks, start=1):
        title = task.get("title", "")
        checked = task.get("checked", False)

        if i == active_index:
            marker = "*(spinner)"
        elif checked:
            marker = "[X]"
        else:
            marker = "[ ]"

        line = f"- {marker} {title}"
        if i == active_index:
            line += "…"
        lines.append(line)

    content = "\n".join(lines)

    dir_path = output_path.parent
    dir_path.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        suffix=".todo",
        prefix=".tmp",
        dir=str(output_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, str(output_path))
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return output_path
