"""Thread-safe SQLite connection helper.

Agent handlers run on worker threads (ThreadPoolExecutor), so the SQLite
stores receive writes from several threads at once. Connections are opened
with ``check_same_thread=False`` and wrapped in a ``ThreadSafeConnection``
that serializes every operation behind a lock. Connections run in autocommit
mode (``isolation_level=None``) so each statement is its own transaction and
no implicit multi-statement transaction can interleave across threads.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any


def connect_threadsafe(db_path: Path) -> ThreadSafeConnection:
    """Open a SQLite connection usable from multiple threads."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
    return ThreadSafeConnection(conn)


class ThreadSafeConnection:
    """Proxy over an ``sqlite3.Connection`` that serializes every call."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.Lock()

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
