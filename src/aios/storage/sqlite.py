"""Base SQLite store with shared lifecycle and low-level helpers.

Every domain store (memory, scheduler, learning, knowledge, telemetry)
follows the same lifecycle: open a thread-safe connection, execute a schema
script, guard every query behind ``is_open`` checks, and surface domain
errors from the ``open()`` boundary.

Subclasses pass the store-specific ``SCHEMA`` string and an optional
``error_class`` so ``open()`` raises the correct domain error on failure.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from aios.storage.errors import StoreError
from aios.storage.threadsafe import ThreadSafeConnection, connect_threadsafe

logger = logging.getLogger("aios.storage.sqlite")


class BaseSQLiteStore:
    """Common SQLite lifecycle shared by every domain store.

    Parameters:
        db_path: Path to the ``.db`` file.
        project_id: Project identifier for row-scoping queries.
        schema: DDL script (``CREATE TABLE`` / ``CREATE INDEX`` statements)
                executed once during ``open()``.
        error_class: Exception class raised when ``open()`` fails. Defaults
                     to :class:`StoreError`; domain stores should pass their
                     own type (e.g. ``KanbanError``).
    """

    def __init__(
        self,
        db_path: Path,
        project_id: str,
        schema: str,
        *,
        error_class: type[Exception] = StoreError,
    ) -> None:
        self._db_path = db_path
        self._project_id = project_id
        self._schema = schema
        self._error_class = error_class
        self._conn: ThreadSafeConnection | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Create directory, open connection, apply PRAGMAs, run schema."""
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise self._error_class(
                f"Cannot create directory: {self._db_path.parent}"
            ) from exc

        try:
            self._conn = connect_threadsafe(self._db_path)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.executescript(self._schema)
            self._post_open()
            self._conn.commit()
        except sqlite3.Error as exc:
            self._conn = None
            raise self._error_class(f"Database open failed: {exc}") from exc

    def _post_open(self) -> None:
        """Hook for subclasses that need post-schema initialization
        (migrations, FTS setup, etc.).  Called inside the open transaction."""

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def is_open(self) -> bool:
        if self._conn is None:
            return False
        try:
            self._conn.execute("SELECT 1")
            return True
        except sqlite3.Error:
            return False

    # ------------------------------------------------------------------
    # Helpers — usable by every subclass
    # ------------------------------------------------------------------

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def _fetch_one(self, query: str, params: tuple = ()) -> tuple | None:
        if not self._conn:
            return None
        try:
            return self._conn.execute(query, params).fetchone()
        except sqlite3.Error:
            return None

    def _fetch_all(self, query: str, params: tuple = ()) -> list[tuple]:
        if not self._conn:
            return []
        try:
            return self._conn.execute(query, params).fetchall()
        except sqlite3.Error:
            return []

    def _execute(self, query: str, params: tuple = ()) -> None:
        if self._conn:
            self._conn.execute(query, params)

    def _commit(self) -> None:
        if self._conn:
            self._conn.commit()
