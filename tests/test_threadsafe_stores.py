"""Concurrent-access tests for thread-safe SQLite stores.

The AgentExecutor runs handlers on a ThreadPoolExecutor, so stores must accept
writes from worker threads without raising ``sqlite3.ProgrammingError``.
"""

from concurrent.futures import ThreadPoolExecutor

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

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(write, range(50)))

        rows = store.get_patterns()
        assert sum(row.usage_count for row in rows) == 50
        store.close()
