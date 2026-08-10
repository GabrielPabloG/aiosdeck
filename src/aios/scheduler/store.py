"""SQLite storage backend. Implementation detail of KanbanEngine."""

import logging
import sqlite3
from pathlib import Path

from aios.scheduler.models import COLUMNS, KanbanBoard, KanbanCard, KanbanError, KanbanSubtask
from aios.storage.sqlite import BaseSQLiteStore

logger = logging.getLogger("aios.scheduler.store")

SCHEMA = """
CREATE TABLE IF NOT EXISTS kanban_boards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    project_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS kanban_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    board_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    column_name TEXT NOT NULL DEFAULT 'Backlog',
    tdd_gate INTEGER NOT NULL DEFAULT 0,
    blocked INTEGER NOT NULL DEFAULT 0,
    block_reason TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (board_id) REFERENCES kanban_boards (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS kanban_subtasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (card_id) REFERENCES kanban_cards (id) ON DELETE CASCADE
);
"""


class KanbanStore(BaseSQLiteStore):
    def __init__(self, db_path: Path, project_id: str) -> None:
        super().__init__(db_path, project_id, SCHEMA, error_class=KanbanError)

    def _post_open(self) -> None:
        if self._conn is None:
            return
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(kanban_cards)")}
        if "blocked" not in columns:
            self._conn.execute(
                "ALTER TABLE kanban_cards ADD COLUMN blocked INTEGER NOT NULL DEFAULT 0"
            )
        if "block_reason" not in columns:
            self._conn.execute(
                "ALTER TABLE kanban_cards ADD COLUMN block_reason TEXT NOT NULL DEFAULT ''"
            )

    def _execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        if not self._conn:
            raise KanbanError("Store is not open")
        return self._conn.execute(query, params)

    def create_board(self, name: str) -> KanbanBoard:
        now = self._now()
        cursor = self._execute(
            "INSERT INTO kanban_boards (name, status, project_id, created_at) "
            "VALUES (?, 'active', ?, ?)",
            (name, self._project_id, now),
        )
        self._commit()
        return KanbanBoard(
            id=cursor.lastrowid,
            name=name,
            status="active",
            project_id=self._project_id,
            created_at=now,
        )

    def get_board(self, board_id: int) -> KanbanBoard | None:
        row = self._fetch_one(
            "SELECT id, name, status, project_id, created_at FROM kanban_boards "
            "WHERE id=? AND project_id=?",
            (board_id, self._project_id),
        )
        return KanbanBoard(*row) if row else None

    def list_boards(self) -> list[KanbanBoard]:
        rows = self._fetch_all(
            "SELECT id, name, status, project_id, created_at FROM kanban_boards "
            "WHERE project_id=? ORDER BY id ASC",
            (self._project_id,),
        )
        return [KanbanBoard(*row) for row in rows]

    def create_card(self, board_id: int, title: str, description: str = "") -> KanbanCard:
        now = self._now()
        cursor = self._execute(
            "INSERT INTO kanban_cards (board_id, title, description, column_name, tdd_gate, "
            "blocked, block_reason, project_id, created_at, updated_at) "
            "VALUES (?, ?, ?, 'Backlog', 0, 0, '', ?, ?, ?)",
            (board_id, title, description, self._project_id, now, now),
        )
        self._commit()
        return KanbanCard(
            id=cursor.lastrowid,
            board_id=board_id,
            title=title,
            description=description,
            column="Backlog",
            tdd_gate=False,
            project_id=self._project_id,
            created_at=now,
            updated_at=now,
            blocked=False,
            block_reason="",
        )

    def get_card(self, card_id: int) -> KanbanCard | None:
        row = self._fetch_one(
            "SELECT id, board_id, title, description, column_name, tdd_gate, "
            "project_id, created_at, updated_at, blocked, block_reason FROM kanban_cards "
            "WHERE id=? AND project_id=?",
            (card_id, self._project_id),
        )
        if not row:
            return None
        card = KanbanCard(*row)
        card.tdd_gate = bool(card.tdd_gate)
        card.blocked = bool(card.blocked)
        card.subtasks = self.get_subtasks(card_id)
        return card

    def list_cards(self, board_id: int) -> list[KanbanCard]:
        rows = self._fetch_all(
            "SELECT id, board_id, title, description, column_name, tdd_gate, "
            "project_id, created_at, updated_at, blocked, block_reason FROM kanban_cards "
            "WHERE board_id=? AND project_id=? ORDER BY id ASC",
            (board_id, self._project_id),
        )
        cards: list[KanbanCard] = []
        for row in rows:
            card = KanbanCard(*row)
            card.tdd_gate = bool(card.tdd_gate)
            card.blocked = bool(card.blocked)
            card.subtasks = self.get_subtasks(card.id)
            cards.append(card)
        return cards

    def move_card(self, card_id: int, column: str) -> KanbanCard:
        if column not in COLUMNS:
            raise KanbanError(f"Unknown kanban column: {column}")

        card = self.get_card(card_id)
        if card is None:
            raise KanbanError(f"Card not found: {card_id}")

        current = card.column
        if column == current:
            return card

        if column == "Done" and not card.tdd_gate:
            raise KanbanError("TDD gate not passed: cannot move to 'Done' without green tests")

        if COLUMNS.index(column) > COLUMNS.index(current) + 1:
            raise KanbanError(f"Cannot skip columns: {current} -> {column}")

        self._execute(
            "UPDATE kanban_cards SET column_name=?, updated_at=? WHERE id=?",
            (column, self._now(), card_id),
        )
        self._commit()
        return self.get_card(card_id)

    def pass_tdd_gate(self, card_id: int) -> None:
        self._execute(
            "UPDATE kanban_cards SET tdd_gate=1, updated_at=? WHERE id=?",
            (self._now(), card_id),
        )
        self._commit()

    def set_blocked(self, card_id: int, reason: str = "") -> KanbanCard:
        self._execute(
            "UPDATE kanban_cards SET blocked=1, block_reason=?, updated_at=? WHERE id=?",
            (reason, self._now(), card_id),
        )
        self._commit()
        return self.get_card(card_id)

    def create_subtask(self, card_id: int, description: str) -> KanbanSubtask:
        now = self._now()
        cursor = self._execute(
            "INSERT INTO kanban_subtasks (card_id, description, done, created_at) "
            "VALUES (?, ?, 0, ?)",
            (card_id, description, now),
        )
        self._commit()
        return KanbanSubtask(
            id=cursor.lastrowid,
            card_id=card_id,
            description=description,
            done=False,
            created_at=now,
        )

    def get_subtasks(self, card_id: int) -> list[KanbanSubtask]:
        rows = self._fetch_all(
            "SELECT id, card_id, description, done, created_at FROM kanban_subtasks "
            "WHERE card_id=? ORDER BY id ASC",
            (card_id,),
        )
        return [
            KanbanSubtask(id=r[0], card_id=r[1], description=r[2], done=bool(r[3]), created_at=r[4])
            for r in rows
        ]

    def complete_subtask(self, subtask_id: int) -> None:
        self._execute("UPDATE kanban_subtasks SET done=1 WHERE id=?", (subtask_id,))
        self._commit()
