"""Tests for TelemetryWriter — buffered async batch writes.

The writer owns all write-path concurrency: events are enqueued in O(1) and
flushed to the store in batched, single-transaction writes. Reads must call
:meth:`TelemetryWriter.flush` first (the consistency boundary owned by
TelemetryEngine). These tests drive the writer through a fake store so the
contract is explicit: the writer only ever needs ``atomic()`` and
``insert_many(table, rows)``.
"""

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from aios.storage.threadsafe import ThreadSafeConnection
from aios.telemetry.store import TelemetryStore
from aios.telemetry.writer import TelemetryWriter


def _wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition not met within timeout")


class _FakeStore:
    """Duck-typed store recording insert_many calls and serialization depth."""

    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self.flush_calls: list[tuple[str, int]] = []
        self.attempts = 0
        self.locked_remaining = 0
        self.constraint_tables: set[str] = set()
        self._inflight = 0
        self.max_inflight = 0
        self._lock = threading.Lock()

    @contextmanager
    def atomic(self):
        yield

    def insert_many(self, table: str, rows: list[dict]) -> None:
        with self._lock:
            self.attempts += 1
            self._inflight += 1
            self.max_inflight = max(self.max_inflight, self._inflight)
        try:
            if self.locked_remaining > 0:
                self.locked_remaining -= 1
                raise sqlite3.OperationalError("database is locked")
            if table in self.constraint_tables:
                raise sqlite3.IntegrityError("UNIQUE constraint failed")
            with self._lock:
                self.flush_calls.append((table, len(rows)))
                self.tables.setdefault(table, []).extend(rows)
        finally:
            with self._lock:
                self._inflight -= 1


class _SpyConnection:
    """Raw-connection proxy that records every executed statement."""

    def __init__(self, real):
        self._real = real
        self.statements: list[str] = []

    def execute(self, sql, params=()):
        self.statements.append(sql)
        return self._real.execute(sql, params)

    def executemany(self, sql, seq):
        self.statements.append(sql)
        return self._real.executemany(sql, seq)

    def commit(self):
        self.statements.append("COMMIT")
        self._real.commit()

    def rollback(self):
        self.statements.append("ROLLBACK")
        self._real.rollback()

    def close(self):
        self._real.close()

    def __getattr__(self, name):
        return getattr(self._real, name)


class TestThresholdAndInterval:
    def test_telemetry_flushes_on_threshold(self):
        store = _FakeStore()
        writer = TelemetryWriter(store, batch_size=5, flush_interval=5.0)
        for i in range(5):
            writer.enqueue("usage", {"i": i})

        _wait_for(lambda: len(store.tables.get("usage", [])) == 5)
        assert [r["i"] for r in store.tables["usage"]] == [0, 1, 2, 3, 4]
        writer.shutdown()

    def test_telemetry_flushes_on_interval(self):
        store = _FakeStore()
        writer = TelemetryWriter(store, batch_size=1000, flush_interval=0.02)
        writer.enqueue("usage", {"i": 1})

        _wait_for(lambda: store.tables.get("usage") == [{"i": 1}])
        writer.shutdown()


class TestShutdown:
    def test_telemetry_shutdown_flushes_remaining(self):
        store = _FakeStore()
        writer = TelemetryWriter(store, batch_size=100, flush_interval=5.0)
        for i in range(3):
            writer.enqueue("gates", {"i": i})

        writer.shutdown()

        assert [r["i"] for r in store.tables["gates"]] == [0, 1, 2]
        assert writer.metrics()["buffer_size"] == 0

    def test_no_double_flush_race_on_shutdown_and_timer(self):
        store = _FakeStore()
        writer = TelemetryWriter(store, batch_size=3, flush_interval=0.005)
        for i in range(10):
            writer.enqueue("usage", {"i": i})

        writer.shutdown()

        assert len(store.tables["usage"]) == 10

    def test_double_shutdown_is_idempotent(self):
        store = _FakeStore()
        writer = TelemetryWriter(store, batch_size=100, flush_interval=5.0)
        writer.enqueue("usage", {"i": 1})

        writer.shutdown()
        writer.shutdown()

        assert len(store.tables["usage"]) == 1


class TestBatching:
    def test_telemetry_writes_are_batched_in_transaction(self):
        raw = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
        spy = _SpyConnection(raw)
        conn = ThreadSafeConnection(spy)
        store = TelemetryStore(Path(":memory:"), "project-1", connection=conn)
        store.open()
        writer = TelemetryWriter(store, batch_size=100, flush_interval=5.0)

        for i in range(3):
            writer.enqueue(
                "executions",
                {
                    "execution_id": f"e{i}",
                    "event_id": f"evt-{i}",
                    "agent": "planner",
                    "status": "ok",
                },
            )
        writer.flush()

        assert spy.statements.count("BEGIN IMMEDIATE") == 1
        assert spy.statements.count("COMMIT") == 1
        assert len(store.query_executions()) == 3
        writer.shutdown()
        store.close()

    def test_heterogeneous_batch_groups_by_table(self):
        store = _FakeStore()
        writer = TelemetryWriter(store, batch_size=100, flush_interval=5.0)
        writer.enqueue("executions", {"event_id": "a"})
        writer.enqueue("usage", {"event_id": "b"})
        writer.enqueue("executions", {"event_id": "c"})

        writer.flush()

        assert store.tables["executions"] == [{"event_id": "a"}, {"event_id": "c"}]
        assert store.tables["usage"] == [{"event_id": "b"}]
        writer.shutdown()

    def test_heterogeneous_batch_lands_in_tables(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()
        writer = TelemetryWriter(store, batch_size=100, flush_interval=5.0)

        writer.enqueue(
            "executions",
            {"execution_id": "e1", "event_id": "evt-1", "agent": "planner", "status": "ok"},
        )
        writer.enqueue(
            "usage",
            {"execution_id": "e1", "agent": "planner", "model": "m", "input_tokens": 10},
        )
        writer.enqueue("costs", {"execution_id": "e1", "total_cost": 0.5})
        writer.flush()

        assert len(store.query_executions()) == 1
        assert len(store.query_usage()) == 1
        assert len(store.query_costs()) == 1
        writer.shutdown()
        store.close()


class TestDrops:
    def test_telemetry_drops_when_buffer_full_increments_counter(self):
        store = _FakeStore()
        writer = TelemetryWriter(store, batch_size=100, flush_interval=5.0, buffer_size=3)
        for i in range(5):
            writer.enqueue("usage", {"i": i})

        metrics = writer.metrics()
        assert metrics["events_dropped_total"] == 2
        assert metrics["buffer_size"] == 3

        writer.shutdown()
        assert len(store.tables["usage"]) == 3


class TestReadContract:
    def test_flush_makes_buffered_events_visible_to_reads(self):
        store = _FakeStore()
        writer = TelemetryWriter(store, batch_size=100, flush_interval=5.0)
        writer.enqueue("retrieval", {"agent": "t"})

        assert "retrieval" not in store.tables  # still buffered

        writer.flush()

        assert store.tables["retrieval"] == [{"agent": "t"}]
        writer.shutdown()

    def test_concurrent_flush_and_read_is_serialized(self):
        store = _FakeStore()
        writer = TelemetryWriter(store, batch_size=1, flush_interval=0.001)
        stop = threading.Event()

        def worker():
            while not stop.is_set():
                writer.flush()

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for i in range(100):
            writer.enqueue("usage", {"i": i})
        stop.set()
        for t in threads:
            t.join()

        writer.flush()

        assert len(store.tables.get("usage", [])) == 100
        assert store.max_inflight == 1  # flushes never interleave
        writer.shutdown()


class TestRetry:
    def test_retry_reenqueues_and_succeeds_after_lock_clears(self):
        store = _FakeStore()
        store.locked_remaining = 2
        writer = TelemetryWriter(store, batch_size=100, flush_interval=5.0, backoff=(0, 0, 0))
        writer.enqueue("usage", {"i": 1})

        writer.flush()

        assert store.attempts == 3
        assert store.tables["usage"] == [{"i": 1}]
        assert writer.metrics()["events_dropped_total"] == 0
        assert writer.metrics()["buffer_size"] == 0
        writer.shutdown()

    def test_persistent_lock_drops_batch_with_counter(self):
        store = _FakeStore()
        store.locked_remaining = 100
        writer = TelemetryWriter(store, batch_size=100, flush_interval=5.0, backoff=(0, 0, 0))
        writer.enqueue("usage", {"i": 1})

        writer.flush()

        assert store.attempts == 4  # initial + 3 backoff retries
        assert "usage" not in store.tables
        assert writer.metrics()["events_dropped_total"] == 1
        writer.shutdown()

    def test_constraint_error_drops_batch_without_retry(self):
        store = _FakeStore()
        store.constraint_tables.add("gates")
        writer = TelemetryWriter(store, batch_size=100, flush_interval=5.0, backoff=(0, 0, 0))
        writer.enqueue("gates", {"gate": "x"})

        writer.flush()

        assert store.attempts == 1
        assert writer.metrics()["events_dropped_total"] == 1
        assert writer.metrics()["buffer_size"] == 0
        writer.shutdown()
