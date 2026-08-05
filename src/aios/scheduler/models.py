"""Kanban data models — domain, not database."""

from dataclasses import dataclass, field

COLUMNS = ("Backlog", "Todo", "InProgress", "Review", "Done")


class KanbanError(Exception):
    """Domain error for kanban flow violations. Hides SQLite from callers."""


@dataclass
class KanbanSubtask:
    id: int | None = None
    card_id: int | None = None
    description: str = ""
    done: bool = False
    created_at: str = ""


@dataclass
class KanbanCard:
    id: int | None = None
    board_id: int | None = None
    title: str = ""
    description: str = ""
    column: str = "Backlog"
    tdd_gate: bool = False
    project_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    subtasks: list[KanbanSubtask] = field(default_factory=list)


@dataclass
class KanbanBoard:
    id: int | None = None
    name: str = ""
    status: str = "active"
    project_id: str = ""
    created_at: str = ""
