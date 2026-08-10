"""Concurrent-access tests for thread-safe SQLite stores.

The AgentExecutor runs handlers on a ThreadPoolExecutor, so stores must accept
writes from worker threads without raising ``sqlite3.ProgrammingError``.

Read-modify-write paths (``add_pattern``, ``upsert_convention``) must not lose
updates: they run inside :meth:`ThreadSafeConnection.atomic`, a ``BEGIN
IMMEDIATE`` transaction that prevents another writer from interleaving between
the SELECT and the write.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from aios.memory.store import SQLiteStore
from aios.storage.threadsafe import connect_threadsafe
from aios.telemetry.store import TelemetryStore


class TestThreadSafeConnection:
    def test_execute_from_worker_threads(self, tmp_path):
        conn = connect_threadsafe(tmp_path / "raw.db")
        conn.execute("CREATE TABLE t (i INTEGER)")
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(lambda n=n: conn.execute("INSERT INTO t VALUES (?)", (n,)))
                for n in range(50)
            ]
            for fut in futures:
                fut.result()
        row = conn.execute("SELECT COUNT(*) FROM t").fetchone()
        assert row[0] == 50
        conn.close()

    def test_atomic_commits_on_success(self, tmp_path):
        conn = connect_threadsafe(tmp_path / "atomic.db")
        conn.execute("CREATE TABLE t (i INTEGER)")
        with conn.atomic():
            conn.execute("INSERT INTO t VALUES (?)", (1,))
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
        conn.close()

    def test_atomic_rolls_back_on_error(self, tmp_path):
        conn = connect_threadsafe(tmp_path / "atomic.db")
        conn.execute("CREATE TABLE t (i INTEGER)")
        with pytest.raises(RuntimeError):
            with conn.atomic():
                conn.execute("INSERT INTO t VALUES (?)", (1,))
                raise RuntimeError("boom")
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
        conn.close()

    def test_atomic_isolation_across_threads(self, tmp_path):
        conn = connect_threadsafe(tmp_path / "atomic.db")
        conn.execute("CREATE TABLE counters (name TEXT PRIMARY KEY, value INTEGER)")
        conn.execute("INSERT INTO counters VALUES ('c', 0)")

        def bump() -> None:
            with conn.atomic():
                (value,) = conn.execute("SELECT value FROM counters WHERE name='c'").fetchone()
                conn.execute("UPDATE counters SET value=? WHERE name='c'", (value + 1,))

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: bump(), range(200)))

        (value,) = conn.execute("SELECT value FROM counters WHERE name='c'").fetchone()
        assert value == 200
        conn.close()


class TestTelemetryStoreConcurrent:
    def test_insert_from_worker_threads(self, tmp_path):
        db = tmp_path / "telemetry.db"
        store = TelemetryStore(db, "project-1")
        store.open()

        def write(i: int) -> None:
            store.insert_execution(
                {
                    "execution_id": f"exec-{i}",
                    "event_id": f"evt-{i}",
                    "agent": "planner",
                    "status": "succeeded",
                    "timestamp": "2026-01-01T00:00:00Z",
                }
            )

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(write, range(50)))

        assert len(store.query_executions()) == 50
        store.close()

    def test_insert_and_query_from_worker_threads(self, tmp_path):
        db = tmp_path / "telemetry.db"
        store = TelemetryStore(db, "project-1")
        store.open()

        def work(i: int) -> None:
            store.insert_usage(
                {
                    "execution_id": f"exec-{i}",
                    "agent": "planner",
                    "model": "gpt-4o",
                    "input_tokens": i,
                    "timestamp": "2026-01-01T00:00:00Z",
                }
            )

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(work, range(30)))

        assert len(store.query_usage(agent="planner")) == 30
        store.close()


class TestMemoryStoreConcurrent:
    def test_read_modify_write_from_worker_threads(self, tmp_path):
        db = tmp_path / "memory.db"
        store = SQLiteStore(db, "project-1")
        store.open()

        def write(i: int) -> None:
            store.add_pattern(name=f"pattern-{i % 5}", description=f"desc-{i}")

        for _ in range(10):
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(write, range(50)))

        rows = store.get_patterns()
        assert sum(row.usage_count for row in rows) == 500
        store.close()

    def test_upsert_convention_from_worker_threads(self, tmp_path):
        db = tmp_path / "memory.db"
        store = SQLiteStore(db, "project-1")
        store.open()

        def write(i: int) -> None:
            store.upsert_convention(rule=f"rule-{i % 5}", category="code", source="test")

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(write, range(50)))

        assert len(store.get_conventions()) == 5
        store.close()
