"""ConnectionPool reuse and lifecycle tests (Issue #38)."""

import sqlite3
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aios.storage.pool import ConnectionPool


def test_pool_returns_same_connection(tmp_path):
    pool = ConnectionPool()
    db = tmp_path / "nested" / "memory.db"
    conn1 = pool.get(db)
    conn2 = pool.get(db)
    assert conn1 is conn2
    assert db.parent.exists()
    pool.close_all()


def test_pool_connects_once_per_path(tmp_path, monkeypatch):
    connects = []
    fake_conn = MagicMock()

    def fake_connect(db_path):
        connects.append(db_path)
        return fake_conn

    monkeypatch.setattr("aios.storage.pool.connect_threadsafe", fake_connect)
    pool = ConnectionPool()
    pool.get(tmp_path / "memory.db")
    pool.get(tmp_path / "memory.db")
    assert len(connects) == 1
    assert fake_conn.execute.call_count == 2
    assert any("journal_mode=WAL" in str(call.args[0]) for call in fake_conn.execute.call_args_list)
    assert any("foreign_keys" in str(call.args[0]) for call in fake_conn.execute.call_args_list)


def test_pool_different_paths_different_connections(tmp_path):
    pool = ConnectionPool()
    conn_a = pool.get(tmp_path / "a.db")
    conn_b = pool.get(tmp_path / "b.db")
    assert conn_a is not conn_b
    pool.close_all()


def test_pool_normalizes_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pool = ConnectionPool()
    relative = pool.get(Path("memory.db"))
    absolute = pool.get(tmp_path / "memory.db")
    assert relative is absolute
    pool.close_all()


def test_pool_thread_safe(tmp_path):
    pool = ConnectionPool()
    db = tmp_path / "memory.db"
    seen: list = []
    lock = threading.Lock()

    def worker():
        for _ in range(10):
            conn = pool.get(db)
            with lock:
                seen.append(id(conn))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(seen) == 80
    assert len(set(seen)) == 1
    pool.close_all()


def test_pool_close_all_idempotent(tmp_path):
    pool = ConnectionPool()
    db = tmp_path / "memory.db"
    conn = pool.get(db)
    conn.execute("SELECT 1")
    pool.close_all()
    pool.close_all()
    with pytest.raises(sqlite3.Error):
        conn.execute("SELECT 1")
    fresh = pool.get(db)
    assert fresh is not conn
    fresh.execute("SELECT 1")
    pool.close_all()
