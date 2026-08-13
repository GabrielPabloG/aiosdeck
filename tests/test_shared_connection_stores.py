"""Shared-connection injection across domain stores (Issue #38)."""

import pytest

from aios.knowledge.store import SQLiteKnowledgeStore
from aios.learning.models import ObservationRecord
from aios.learning.store import LearningStore
from aios.memory.store import SQLiteStore
from aios.scheduler.store import KanbanStore
from aios.storage.errors import StoreError
from aios.storage.sqlite import BaseSQLiteStore
from aios.storage.threadsafe import connect_threadsafe
from aios.telemetry.store import TelemetryError, TelemetryStore


def test_all_engine_schemas_apply_to_shared_connection(tmp_path):
    db = tmp_path / "memory.db"
    conn = connect_threadsafe(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")

    memory = SQLiteStore(db, "proj", connection=conn)
    scheduler = KanbanStore(db, "proj", connection=conn)
    learning = LearningStore(db, "proj", connection=conn)
    knowledge = SQLiteKnowledgeStore(db, "proj", connection=conn)
    telemetry = TelemetryStore(db, "proj", connection=conn)
    for store in (memory, scheduler, learning, knowledge, telemetry):
        store.open()

    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    for expected in (
        "conventions",
        "kanban_boards",
        "learning_observations",
        "knowledge_sources",
        "telemetry_executions",
    ):
        assert expected in tables

    memory.add_pattern("shared-pattern", "desc")
    assert any(p.name == "shared-pattern" for p in memory.get_patterns())

    board = scheduler.create_board("shared-board")
    assert scheduler.get_board(board.id).name == "shared-board"

    obs_id = learning.insert_observation(ObservationRecord(content="shared-obs"))
    assert learning.get_observation(obs_id).content == "shared-obs"

    knowledge.start_run("shared-run")
    assert knowledge.get_last_run()["run_id"] == "shared-run"

    telemetry.insert_execution({"event_id": "evt-shared", "execution_id": "exec-shared"})
    assert any(r["event_id"] == "evt-shared" for r in telemetry.query_executions(limit=10))


def test_store_close_does_not_close_injected_connection(tmp_path):
    db = tmp_path / "memory.db"
    conn = connect_threadsafe(db)
    memory = SQLiteStore(db, "proj", connection=conn)
    memory.open()
    memory.add_pattern("kept", "d")
    scheduler = KanbanStore(db, "proj", connection=conn)
    scheduler.open()

    memory.close()
    assert not memory.is_open()
    scheduler.create_board("still-alive")
    conn.execute("SELECT 1")


def test_open_failure_preserves_shared_connection(tmp_path):
    db = tmp_path / "memory.db"
    conn = connect_threadsafe(db)
    store = BaseSQLiteStore(db, "proj", "THIS IS NOT VALID SQL", connection=conn)
    with pytest.raises(StoreError):
        store.open()
    conn.execute("SELECT 1")
    store.close()


def test_telemetry_open_failure_preserves_shared_connection(tmp_path):
    db = tmp_path / "memory.db"
    conn = connect_threadsafe(db)
    conn.execute("CREATE TABLE telemetry_executions (id INTEGER PRIMARY KEY)")
    store = TelemetryStore(db, "proj", connection=conn)
    with pytest.raises(TelemetryError):
        store.open()
    conn.execute("SELECT 1")


def test_backward_compatible_self_connection(tmp_path):
    db = tmp_path / "memory.db"
    store = SQLiteStore(db, "proj")
    store.open()
    store.add_pattern("self-owned", "d")
    assert store.is_open()
    store.close()
    assert not store.is_open()

    telemetry = TelemetryStore(db, "proj")
    telemetry.open()
    assert telemetry.is_open()
    telemetry.close()
    assert not telemetry.is_open()
