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


def test_gate_event_passed(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    event = MagicMock()
    event.topic = "quality.gate_passed"
    event.correlation_id = "corr-001"
    event.payload = {
        "gate": "lint",
        "status": "passed",
        "duration_ms": 150,
        "findings_low": 1,
        "findings_medium": 0,
        "findings_high": 0,
        "findings_critical": 0,
        "blocked": False,
        "overridden": False,
    }
    engine._on_gate_event(event)

    engine._flush_on_read()
    rows = engine._store.query_gate_records(gate="lint")
    assert len(rows) == 1
    assert rows[0]["status"] == "passed"
    assert rows[0]["gate"] == "lint"

    engine.shutdown()


def test_gate_event_via_topic_mapping(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    event = MagicMock()
    event.topic = "quality.gate_failed"
    event.correlation_id = "corr-002"
    event.payload = {"gate": "security", "findings": {"high": 2}}
    engine._on_gate_event(event)

    engine._flush_on_read()
    rows = engine._store.query_gate_records(gate="security")
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert rows[0]["findings_high"] == 2

    engine.shutdown()


def test_gate_event_non_dict_payload_ignored(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    event = MagicMock()
    event.topic = "quality.gate_passed"
    event.payload = "not a dict"
    engine._on_gate_event(event)

    engine._flush_on_read()
    rows = engine._store.query_gate_records()
    assert len(rows) == 0

    engine.shutdown()


def test_security_event(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    event = MagicMock()
    event.correlation_id = "corr-003"
    event.payload = {
        "decision": "allow",
        "agent": "planner",
        "action": "file.write",
        "allowed": True,
        "reason": "policy allows",
        "violations": [],
        "intent_source": "user",
    }
    engine._on_security_event(event)

    engine._flush_on_read()
    rows = engine._store.query_security_records()
    assert len(rows) == 1
    assert rows[0]["decision"] == "allow"
    assert rows[0]["agent"] == "planner"
    assert rows[0]["action"] == "file.write"
    assert rows[0]["allowed"] == True

    engine.shutdown()


def test_routing_event_all_fields(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    event = MagicMock()
    event.correlation_id = "corr-004"
    event.payload = {
        "agent": "planner",
        "task_type": "code",
        "complexity": "high",
        "provider": "openai",
        "model": "gpt-4o",
        "variant": "turbo",
        "reason": "best match",
        "estimated_cost": 0.05,
        "context_size": 8000,
        "source": "rule",
        "fallback_used": True,
        "fallback_reason": "primary unavailable",
    }
    engine._on_routing_event(event)

    engine._flush_on_read()
    rows = engine._store.query_routing_records()
    assert len(rows) == 1
    assert rows[0]["agent"] == "planner"
    assert rows[0]["model"] == "gpt-4o"
    assert rows[0]["provider"] == "openai"
    assert rows[0]["variant"] == "turbo"
    assert rows[0]["fallback_used"] is True
    assert rows[0]["fallback_reason"] == "primary unavailable"

    engine.shutdown()


def test_routing_event_defaults(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    event = MagicMock()
    event.correlation_id = ""
    event.payload = {}
    engine._on_routing_event(event)

    engine._flush_on_read()
    rows = engine._store.query_routing_records()
    assert len(rows) == 1
    assert rows[0]["agent"] == ""
    assert rows[0]["model"] == ""
    assert rows[0]["estimated_cost"] == 0.0
    assert rows[0]["context_size"] == 0
    assert rows[0]["fallback_used"] is False

    engine.shutdown()


def test_backlog_event_all_fields(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    event = MagicMock()
    event.correlation_id = "corr-005"
    event.payload = {
        "run_id": "run-001",
        "task_index": 3,
        "task_title": "Fix bug",
        "task_type": "bugfix",
        "task_scope": "backend",
        "status": "completed",
        "commit_sha": "abc123",
        "duration_ms": 500,
        "error": "",
        "source": "backlog",
    }
    engine._on_backlog_event(event)

    engine._flush_on_read()
    rows = engine._store.query_backlog_stats(run_id="run-001")
    assert len(rows) == 1
    assert rows[0]["run_id"] == "run-001"
    assert rows[0]["task_index"] == 3
    assert rows[0]["task_title"] == "Fix bug"
    assert rows[0]["task_type"] == "bugfix"
    assert rows[0]["task_scope"] == "backend"
    assert rows[0]["status"] == "completed"
    assert rows[0]["commit_sha"] == "abc123"
    assert rows[0]["duration_ms"] == 500

    engine.shutdown()


def test_backlog_event_non_dict_ignored(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    event = MagicMock()
    event.payload = [1, 2, 3]
    engine._on_backlog_event(event)

    engine._flush_on_read()
    rows = engine._store.query_backlog_stats()
    assert len(rows) == 0

    engine.shutdown()


def test_query_when_store_is_none():
    engine = TelemetryEngine(project_path=None)
    result = engine.query()
    assert result["totals"] == {}
    assert result["records"] == []
    assert result["cost_records"] == []
    assert result["executions"] == []
    assert result["total_records"] == 0
    assert result["total_executions"] == 0
    assert engine.query_routing_stats() == []
    assert engine.query_routing_records() == []
    assert engine.query_route_accuracy() == []
    assert engine.query_backlog_stats() == []
    assert engine.query_gate_stats() == []
    assert engine.query_gate_records() == []
    assert engine.query_security_stats() == []
    assert engine.query_security_records() == []
    assert engine.query_skill_stats() == []


def test_double_subscribe_guard(tmp_path):
    db = tmp_path / "test.db"
    bus = MagicMock()
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.set_event_bus(bus)
    engine._subscribe()
    call_count_before = bus.subscribe.call_count
    engine._subscribe()
    assert bus.subscribe.call_count == call_count_before
    engine._unsubscribe()
