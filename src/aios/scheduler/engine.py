"""Kanban Engine — scrum board persistence and TDD flow enforcement.

SQLite is an implementation detail. This is the public abstraction.

The store reuses the project-scoped database (default ./.aios/memory.db)
with dedicated kanban_ tables, keeping one SQLite file per project.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from aios.events.events import (
    KANBAN_CARD_BLOCKED,
    KANBAN_CARD_MOVED,
    KANBAN_SUBTASK_COMPLETED,
    KANBAN_SUBTASK_CREATED,
)
from aios.scheduler.models import KanbanBoard, KanbanCard, KanbanError, KanbanSubtask
from aios.scheduler.store import KanbanStore

logger = logging.getLogger("aios.scheduler")


class KanbanEngine:
    name = "scheduler"

    def __init__(
        self,
        project_path: Path | None = None,
        db_path: str | None = None,
        event_bus=None,
    ) -> None:
        self._project_path = project_path or Path.cwd()
        self._project_id = self._project_path.resolve().as_posix()
        self._db_path = self._resolve_db_path(db_path)
        self._store: KanbanStore | None = None
        self._bus = event_bus

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
        old_column = None
        if self._bus is not None:
            card = self._store.get_card(card_id)
            old_column = card.column if card else None

        try:
            result = self._store.move_card(card_id, column)
        except KanbanError:
            if column == "Done" and self._bus is not None:
                card = self._store.get_card(card_id)
                if card is not None:
                    self._bus.publish(
                        KANBAN_CARD_BLOCKED,
                        {
                            "card_id": card.id,
                            "card_title": card.title,
                            "reason": (
                                "TDD gate not passed: cannot move to 'Done' without green tests"
                            ),
                            "column": card.column,
                            "board_id": card.board_id,
                        },
                    )
            raise

        if self._bus is not None and old_column != result.column:
            self._bus.publish(
                KANBAN_CARD_MOVED,
                {
                    "card_id": result.id,
                    "card_title": result.title,
                    "from_column": old_column,
                    "to_column": result.column,
                    "board_id": result.board_id,
                },
            )
        return result

    def block_card(self, card_id: int, reason: str = "") -> KanbanCard:
        result = self._store.set_blocked(card_id, reason)
        if self._bus is not None:
            self._bus.publish(
                KANBAN_CARD_BLOCKED,
                {
                    "card_id": result.id,
                    "card_title": result.title,
                    "reason": reason,
                    "column": result.column,
                    "board_id": result.board_id,
                },
            )
        return result

    def pass_tdd_gate(self, card_id: int) -> None:
        self._store.pass_tdd_gate(card_id)

    def begin_work(self, card_id: int) -> KanbanCard:
        """Move a card to the active work column for the current flow."""
        self.move_card(card_id, "Todo")
        return self.move_card(card_id, "InProgress")

    def complete_work(self, card_id: int) -> KanbanCard:
        """Move a card to the done column for the current flow, gate included."""
        self.move_card(card_id, "Review")
        self.pass_tdd_gate(card_id)
        return self.move_card(card_id, "Done")

    def create_subtask(self, card_id: int, description: str) -> KanbanSubtask:
        subtask = self._store.create_subtask(card_id, description)
        if self._bus is not None:
            self._bus.publish(
                KANBAN_SUBTASK_CREATED,
                {
                    "subtask_id": subtask.id,
                    "card_id": subtask.card_id,
                    "description": subtask.description,
                },
            )
        return subtask

    def complete_subtask(self, subtask_id: int) -> None:
        self._store.complete_subtask(subtask_id)
        if self._bus is not None:
            self._bus.publish(
                KANBAN_SUBTASK_COMPLETED,
                {"subtask_id": subtask_id},
            )

    def set_event_bus(self, bus) -> None:
        self._bus = bus

    def _resolve_db_path(self, override: str | None) -> Path:
        if override:
            return Path(override)

        env = os.environ.get("AIOS_MEMORY_PATH")
        if env is not None:
            return Path(env)

        return self._project_path / ".aios" / "memory.db"
