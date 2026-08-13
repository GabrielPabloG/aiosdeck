"""Tests for TelemetryEngine — event subscription and persistence."""

from unittest.mock import MagicMock

from aios.telemetry.engine import TelemetryEngine


def test_engine_initializes(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()
    assert engine.health_check() is True
    engine.shutdown()


def test_engine_health_check_not_initialized():
    engine = TelemetryEngine(project_path=None)
    assert engine.health_check() is True


def test_engine_shutdown_closes_store(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()
    engine.shutdown()
    assert engine._store is None


def test_engine_query_empty(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()
    result = engine.query()
    assert result["totals"] != {}
    engine.shutdown()


def test_persist_execution_from_event(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    event = MagicMock()
    event.payload = {
        "execution_id": "exec-001",
        "event_id": "evt-001",
        "correlation_id": "corr-001",
        "agent": "planner",
        "task_id": "task-001",
        "status": "succeeded",
        "duration_ms": 1200.0,
        "attempt": 1,
        "timestamp": "2026-01-01T00:00:00Z",
    }
    engine._on_execution_event(event)

    result = engine.query(agent="planner")
    assert len(result["records"]) == 0  # no usage, only execution

    rows = engine._store.query_executions(agent="planner")
    assert len(rows) == 1
    assert rows[0]["execution_id"] == "exec-001"

    engine.shutdown()


def test_persist_usage_from_completed_event(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    event = MagicMock()
    event.payload = {
        "execution_id": "exec-001",
        "event_id": "evt-001",
        "agent": "planner",
        "status": "succeeded",
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "model": "gpt-4o",
            "provider": "openai",
            "timestamp": "2026-01-01T00:00:00Z",
        },
    }
    engine._on_execution_event(event)

    result = engine.query(agent="planner")
    assert len(result["records"]) == 1
    assert result["totals"]["input_tokens"] == 100
    assert result["totals"]["output_tokens"] == 50

    engine.shutdown()


def test_completed_event_without_usage_is_ignored_for_usage(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    event = MagicMock()
    event.payload = {
        "execution_id": "exec-001",
        "event_id": "evt-001",
        "agent": "planner",
        "status": "failed",
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
        },
    }
    engine._on_execution_event(event)

    result = engine.query(agent="planner")
    assert len(result["records"]) == 0

    engine.shutdown()


def test_lifecycle_event_persisted_only_as_execution(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    event = MagicMock()
    event.payload = {
        "execution_id": "exec-001",
        "event_id": "evt-001",
        "agent": "planner",
        "status": "running",
    }
    engine._on_lifecycle_event(event)

    rows = engine.query(agent="planner")["executions"]
    assert len(rows) == 1

    result = engine.query(agent="planner")
    assert len(result["records"]) == 0

    engine.shutdown()


def test_query_flushes_pending_events_before_read(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    event = MagicMock()
    event.payload = {
        "execution_id": "exec-001",
        "event_id": "evt-001",
        "agent": "planner",
        "status": "running",
    }
    engine._on_lifecycle_event(event)

    assert engine._writer.metrics()["buffer_size"] == 1  # still buffered

    result = engine.query(agent="planner")
    assert len(result["executions"]) == 1
    assert engine._writer.metrics()["buffer_size"] == 0

    engine.shutdown()


def test_subscribe_and_unsubscribe(tmp_path):
    db = tmp_path / "test.db"
    bus = MagicMock()
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.set_event_bus(bus)
    engine._subscribe()
    engine._unsubscribe()
    assert engine._subscription_count == 0
