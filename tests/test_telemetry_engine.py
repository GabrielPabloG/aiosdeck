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
    assert rows[0]["allowed"]

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


# ---------------------------------------------------------------------------
# Cycle 1: high-density contract tests targeting surviving mutants
# ---------------------------------------------------------------------------


def test_persist_execution_record_has_all_keys(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    event = MagicMock()
    event.correlation_id = "corr-x"
    event.payload = {
        "execution_id": "e1",
        "event_id": "evt1",
        "correlation_id": "corr-1",
        "task_id": "task-1",
        "workflow_id": "wf-1",
        "agent": "planner",
        "model": "gpt-4o",
        "provider": "openai",
        "runtime": "opencode",
        "attempt": 2,
        "status": "succeeded",
        "duration_ms": 123.4,
        "timestamp": "2026-01-01T00:00:00Z",
        "observability": {
            "tool_calls": 5,
            "llm_turns": 3,
            "total_cost": 0.01,
        },
    }
    engine._on_execution_event(event)

    engine._flush_on_read()
    rows = engine._store.query_executions(agent="planner")
    assert len(rows) == 1
    r = rows[0]
    assert r["execution_id"] == "e1"
    assert r["event_id"] == "evt1"
    assert r["correlation_id"] == "corr-1"
    assert r["task_id"] == "task-1"
    assert r["workflow_id"] == "wf-1"
    assert r["agent"] == "planner"
    assert r["model"] == "gpt-4o"
    assert r["provider"] == "openai"
    assert r["runtime"] == "opencode"
    assert r["attempt"] == 2
    assert r["status"] == "succeeded"
    assert r["duration_ms"] == 123.4
    assert r["timestamp"] == "2026-01-01T00:00:00Z"

    # query_executions does not return these columns; verify directly in DB.
    db_row = engine._store._conn.execute(
        "SELECT tool_calls, llm_turns, total_cost FROM telemetry_executions WHERE execution_id = ?",
        ("e1",),
    ).fetchone()
    assert db_row[0] == 5
    assert db_row[1] == 3
    assert db_row[2] == 0.01

    engine.shutdown()


def test_persist_execution_defaults_when_fields_missing(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    event = MagicMock()
    event.correlation_id = ""
    event.payload = {
        "execution_id": "e2",
        "agent": "dev",
        "status": "failed",
    }
    engine._on_execution_event(event)

    engine._flush_on_read()
    rows = engine._store.query_executions(agent="dev")
    assert len(rows) == 1
    r = rows[0]
    assert r["execution_id"] == "e2"
    assert r["event_id"]  # auto-generated
    assert r["correlation_id"] == ""
    assert r["task_id"] == ""
    assert r["workflow_id"] is None
    assert r["model"] is None
    assert r["provider"] is None
    assert r["runtime"] is None
    assert r["attempt"] == 1
    assert r["timestamp"]  # generated

    db_row = engine._store._conn.execute(
        "SELECT tool_calls, llm_turns, total_cost FROM telemetry_executions WHERE execution_id = ?",
        ("e2",),
    ).fetchone()
    assert db_row[0] == 0
    assert db_row[1] == 0
    assert db_row[2] == 0.0

    engine.shutdown()


def test_gate_event_all_fields_with_findings_dict(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    event = MagicMock()
    event.topic = "quality.gate_failed"
    event.correlation_id = "corr-gate"
    event.payload = {
        "gate": "security",
        "status": "failed",
        "duration_ms": 200,
        "findings": {"low": 1, "medium": 2, "high": 3, "critical": 4},
        "blocked": True,
        "overridden": False,
        "timestamp": "2026-06-01T12:00:00Z",
    }
    engine._on_gate_event(event)

    engine._flush_on_read()
    rows = engine._store.query_gate_records(gate="security")
    assert len(rows) == 1
    r = rows[0]
    assert r["gate"] == "security"
    assert r["status"] == "failed"
    assert r["correlation_id"] == "corr-gate"
    assert r["duration_ms"] == 200
    assert r["findings_low"] == 1
    assert r["findings_medium"] == 2
    assert r["findings_high"] == 3
    assert r["findings_critical"] == 4
    assert r["blocked"] == 1
    assert r["overridden"] == 0
    assert r["timestamp"] == "2026-06-01T12:00:00Z"

    engine.shutdown()


def test_gate_event_fallback_from_topic_status(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    event = MagicMock()
    event.topic = "quality.gate_blocked"
    event.correlation_id = ""
    event.payload = {"gate": "code", "findings": {}}
    engine._on_gate_event(event)

    engine._flush_on_read()
    rows = engine._store.query_gate_records(gate="code")
    assert len(rows) == 1
    assert rows[0]["status"] == "blocked"
    assert rows[0]["findings_low"] == 0
    assert rows[0]["blocked"] == 0

    engine.shutdown()


def test_gate_event_findings_dict_overrides_flat_keys(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    event = MagicMock()
    event.topic = "quality.gate_passed"
    event.correlation_id = ""
    event.payload = {
        "gate": "quality",
        "findings": {"low": 10},
        "findings_low": 1,
    }
    engine._on_gate_event(event)

    engine._flush_on_read()
    rows = engine._store.query_gate_records(gate="quality")
    assert rows[0]["findings_low"] == 10

    engine.shutdown()


def test_persist_usage_all_fields(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    usage = {
        "model": "gpt-4o",
        "provider": "openai",
        "input_tokens": 100,
        "output_tokens": 50,
        "total_tokens": 150,
        "cached_tokens": 10,
        "reasoning_tokens": 5,
        "context_tokens": 80,
        "provider_raw": {"raw_key": "val"},
        "timestamp": "2026-01-01T00:00:00Z",
    }
    event_payload = {
        "execution_id": "eu-1",
        "agent": "planner",
    }
    engine._persist_usage(usage, event_payload)

    engine._flush_on_read()
    rows = engine._store.query_usage(agent="planner")
    assert len(rows) == 1
    r = rows[0]
    assert r["execution_id"] == "eu-1"
    assert r["agent"] == "planner"
    assert r["model"] == "gpt-4o"
    assert r["provider"] == "openai"
    assert r["input_tokens"] == 100
    assert r["output_tokens"] == 50
    assert r["total_tokens"] == 150
    assert r["cached_tokens"] == 10
    assert r["reasoning_tokens"] == 5
    assert r["context_tokens"] == 80
    assert r["timestamp"] == "2026-01-01T00:00:00Z"

    engine.shutdown()


def test_persist_usage_computes_total_tokens_when_missing(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    usage = {
        "model": "gpt-4o",
        "provider": "openai",
        "input_tokens": 100,
        "output_tokens": 50,
    }
    engine._persist_usage(usage, {"execution_id": "eu-2", "agent": "dev"})

    engine._flush_on_read()
    rows = engine._store.query_usage(agent="dev")
    assert len(rows) == 1
    assert rows[0]["total_tokens"] == 150

    engine.shutdown()


# ---------------------------------------------------------------------------
# Cycle 2 contract tests — _persist_execution edge cases
# ---------------------------------------------------------------------------


def test_persist_execution_observability_none_uses_payload_fallback(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    event = MagicMock()
    event.payload = {
        "execution_id": "e-obs-none",
        "agent": "dev",
        "status": "succeeded",
        "model": "gpt-4o",
        "provider": "openai",
    }
    engine._on_execution_event(event)

    engine._flush_on_read()
    db_row = engine._store._conn.execute(
        "SELECT model, provider, tool_calls, llm_turns, total_cost "
        "FROM telemetry_executions WHERE execution_id = ?",
        ("e-obs-none",),
    ).fetchone()
    assert db_row[0] == "gpt-4o"
    assert db_row[1] == "openai"
    assert db_row[2] == 0
    assert db_row[3] == 0
    assert db_row[4] == 0.0

    engine.shutdown()


def test_persist_execution_observability_empty_dict_uses_payload_fallback(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    event = MagicMock()
    event.payload = {
        "execution_id": "e-obs-empty",
        "agent": "dev",
        "status": "succeeded",
        "model": "gpt-4o",
        "provider": "openai",
        "observability": {},
    }
    engine._on_execution_event(event)

    engine._flush_on_read()
    db_row = engine._store._conn.execute(
        "SELECT model, provider FROM telemetry_executions WHERE execution_id = ?",
        ("e-obs-empty",),
    ).fetchone()
    assert db_row[0] == "gpt-4o"
    assert db_row[1] == "openai"

    engine.shutdown()


def test_persist_execution_model_from_observability_when_payload_empty(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    event = MagicMock()
    event.payload = {
        "execution_id": "e-obs-model",
        "agent": "dev",
        "status": "succeeded",
        "observability": {"model": "claude-sonnet", "provider": "anthropic"},
    }
    engine._on_execution_event(event)

    engine._flush_on_read()
    db_row = engine._store._conn.execute(
        "SELECT model, provider FROM telemetry_executions WHERE execution_id = ?",
        ("e-obs-model",),
    ).fetchone()
    assert db_row[0] == "claude-sonnet"
    assert db_row[1] == "anthropic"

    engine.shutdown()


def test_persist_execution_non_dict_payload_ignored(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    event = MagicMock()
    event.payload = "not a dict"
    engine._on_execution_event(event)

    engine._flush_on_read()
    rows = engine._store.query_executions(agent="")
    assert len(rows) == 0

    engine.shutdown()


def test_persist_execution_event_id_auto_generated(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    event = MagicMock()
    event.payload = {
        "execution_id": "e-auto",
        "agent": "dev",
        "status": "succeeded",
    }
    engine._on_execution_event(event)

    engine._flush_on_read()
    rows = engine._store.query_executions(agent="dev")
    assert len(rows) == 1
    assert rows[0]["event_id"]  # auto-generated, not empty

    engine.shutdown()


def test_persist_execution_overridden_model_from_payload(tmp_path):
    db = tmp_path / "test.db"
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.initialize()

    event = MagicMock()
    event.payload = {
        "execution_id": "e-override",
        "agent": "dev",
        "status": "succeeded",
        "model": "gpt-4o",
        "provider": "openai",
        "observability": {"model": "claude", "provider": "anthropic"},
    }
    engine._on_execution_event(event)

    engine._flush_on_read()
    db_row = engine._store._conn.execute(
        "SELECT model, provider FROM telemetry_executions WHERE execution_id = ?",
        ("e-override",),
    ).fetchone()
    assert db_row[0] == "gpt-4o"
    assert db_row[1] == "openai"

    engine.shutdown()
