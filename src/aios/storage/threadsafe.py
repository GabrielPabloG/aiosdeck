"""Thread-safe SQLite connection helper.

Agent handlers run on worker threads (ThreadPoolExecutor), so the SQLite
stores receive writes from several threads at once. Connections are opened
with ``check_same_thread=False`` and wrapped in a ``ThreadSafeConnection``
that serializes every operation behind a lock. Connections run in autocommit
mode (``isolation_level=None``) so each statement is its own transaction and
no implicit multi-statement transaction can interleave across threads.

Read-modify-write sequences (SELECT then INSERT/UPDATE) are still subject to
lost updates across threads, so stores wrap them in :meth:`ThreadSafeConnection.atomic`,
which starts an immediate transaction behind the lock and commits or rolls back
as one unit. ``busy_timeout`` makes concurrent writers wait instead of failing
immediately with ``sqlite3.OperationalError: database is locked``.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger("aios.storage.threadsafe")

BUSY_TIMEOUT_MS = 5000


def connect_threadsafe(db_path: Path) -> ThreadSafeConnection:
    """Open a SQLite connection usable from multiple threads."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    return ThreadSafeConnection(conn)


class ThreadSafeConnection:
    """Proxy over an ``sqlite3.Connection`` that serializes every call."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.RLock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Run a read-modify-write block as a single atomic transaction.

        Acquires the connection lock and starts a ``BEGIN IMMEDIATE``
        transaction. ``IMMEDIATE`` takes a reserved write lock up front, so no
        other writer can interleave between the SELECT and the write. The
        transaction is committed on success and rolled back on error.
        """
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def execute(self, sql: str, parameters: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, parameters)

    def executescript(self, sql_script: str) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.executescript(sql_script)

    def commit(self) -> None:
        with self._lock:
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @property
    def total_changes(self) -> int:
        return self._conn.total_changes

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._conn, name)
        if callable(attr):

            def _locked(*args: Any, **kwargs: Any) -> Any:
                with self._lock:
                    return attr(*args, **kwargs)

            return _locked
        return attr
