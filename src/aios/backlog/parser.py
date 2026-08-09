"""Parse conventional commit titles and load tasks from sources."""

import re
from pathlib import Path

from aios.backlog.models import BacklogTask

_CONVENTIONAL_RE = re.compile(r"^(\w+)(?:\(([^)]*)\))?:\s*(.+?)(?:\s*\((v\d+\.\d+\.\d+)\))?$")


def parse_conventional(title: str) -> tuple[str, str, str, str]:
    """Parse a conventional commit title into (type, scope, subject, version).

    Returns ("", "", "", "") when the title does not match.
    """
    m = _CONVENTIONAL_RE.match(title.strip())
    if not m:
        return ("", "", "", "")
    return (m.group(1), m.group(2) or "", m.group(3).strip(), m.group(4) or "")


def load_tasks_from_kanban(engine, board_name: str) -> list[BacklogTask]:
    """Load tasks from cards in the Todo column of a named kanban board."""
    boards = engine.list_boards()
    board = None
    for b in boards:
        if b.name == board_name:
            board = b
            break
    if board is None:
        return []
    cards = engine.list_cards(board.id)
    tasks: list[BacklogTask] = []
    for i, card in enumerate(cards):
        if card.column != "Todo":
            continue
        typ, scope, subject, version = parse_conventional(card.title)
        tasks.append(
            BacklogTask(
                title=card.title,
                type=typ or "feat",
                scope=scope,
                subject=subject or card.title,
                version=version,
                source=f"kanban:{board_name}",
                index=i,
            )
        )
    return tasks


def load_tasks_from_file(path: str | Path) -> list[BacklogTask]:
    """Load tasks from a markdown file with ``- [ ] title`` lines."""
    p = Path(path)
    if not p.exists():
        return []
    tasks: list[BacklogTask] = []
    for i, line in enumerate(p.read_text().splitlines()):
        stripped = line.strip()
        if not stripped.startswith("- [ ] "):
            continue
        title = stripped[6:].strip()
        typ, scope, subject, version = parse_conventional(title)
        tasks.append(
            BacklogTask(
                title=title,
                type=typ or "feat",
                scope=scope,
                subject=subject or title,
                version=version,
                source=f"file:{p.name}",
                index=i,
            )
        )
    return tasks
