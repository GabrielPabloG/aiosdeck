"""Kanban Engine — scrum board persistence and TDD flow enforcement.

SQLite is an implementation detail. This is the public abstraction.

The store reuses the project-scoped database (default ./.aios/memory.db)
with dedicated kanban_ tables, keeping one SQLite file per project.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from aios.scheduler.models import KanbanBoard, KanbanCard, KanbanError, KanbanSubtask
from aios.scheduler.store import KanbanStore

logger = logging.getLogger("aios.scheduler")


class KanbanEngine:
    name = "scheduler"

    def __init__(self, project_path: Path | None = None, db_path: str | None = None) -> None:
        self._project_path = project_path or Path.cwd()
        self._project_id = self._project_path.resolve().as_posix()
        self._db_path = self._resolve_db_path(db_path)
        self._store: KanbanStore | None = None

    def initialize(self) -> None:
        try:
            self._store = KanbanStore(self._db_path, self._project_id)
            self._store.open()
        except KanbanError as exc:
            self._store = None
            raise RuntimeError(str(exc)) from exc

    def health_check(self) -> bool:
        if self._store is None:
            return True
        return self._store.is_open()

    def shutdown(self) -> None:
        if self._store:
            self._store.close()
            self._store = None

    def create_board(self, name: str) -> KanbanBoard:
        return self._store.create_board(name)

    def get_board(self, board_id: int) -> KanbanBoard | None:
        return self._store.get_board(board_id)

    def list_boards(self) -> list[KanbanBoard]:
        return self._store.list_boards()

    def create_card(self, board_id: int, title: str, description: str = "") -> KanbanCard:
        return self._store.create_card(board_id, title, description)

    def get_card(self, card_id: int) -> KanbanCard | None:
        return self._store.get_card(card_id)

    def list_cards(self, board_id: int) -> list[KanbanCard]:
        return self._store.list_cards(board_id)

    def move_card(self, card_id: int, column: str) -> KanbanCard:
        return self._store.move_card(card_id, column)

    def pass_tdd_gate(self, card_id: int) -> None:
        self._store.pass_tdd_gate(card_id)

    def create_subtask(self, card_id: int, description: str) -> KanbanSubtask:
        return self._store.create_subtask(card_id, description)

    def complete_subtask(self, subtask_id: int) -> None:
        self._store.complete_subtask(subtask_id)

    def _resolve_db_path(self, override: str | None) -> Path:
        if override:
            return Path(override)

        env = os.environ.get("AIOS_MEMORY_PATH")
        if env is not None:
            return Path(env)

        return self._project_path / ".aios" / "memory.db"
