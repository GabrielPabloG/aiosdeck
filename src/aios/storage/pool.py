"""Shared SQLite connection pool.

The pool owns the shared connection lifecycle. Stores do not own injected
connections. Every store that uses a given database file receives the same
``ThreadSafeConnection`` for that path, so domain schemas coexist on a
single connection instead of one being opened per store.
"""

from __future__ import annotations

import threading
from pathlib import Path

from aios.storage.threadsafe import ThreadSafeConnection, connect_threadsafe


class ConnectionPool:
    """Registry of one thread-safe SQLite connection per resolved path.

    ``get()`` normalizes the path (relative/absolute) so every store
    addressing the same file shares the same connection. The first
    connection for a path is opened with the standard PRAGMAs (WAL,
    foreign keys); subsequent calls return the cached connection.
    ``close_all()`` closes every connection and clears the registry.
    """

    def __init__(self) -> None:
        self._connections: dict[str, ThreadSafeConnection] = {}
        self._lock = threading.Lock()

    def get(self, db_path: Path | str) -> ThreadSafeConnection:
        key = str(Path(db_path).resolve())
        with self._lock:
            conn = self._connections.get(key)
            if conn is None:
                path = Path(db_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                conn = connect_threadsafe(path)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys = ON")
                self._connections[key] = conn
            return conn

    def close_all(self) -> None:
        with self._lock:
            for conn in self._connections.values():
                conn.close()
            self._connections.clear()
