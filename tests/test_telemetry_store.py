"""Tests for TelemetryStore — schema, CRUD, isolation."""

import sqlite3
from pathlib import Path

import pytest

from aios.storage.threadsafe import connect_threadsafe
from aios.telemetry.store import TelemetryError, TelemetryStore


def _open_store(tmp_path, project="project-1"):
    store = TelemetryStore(tmp_path / "test.db", project)
    store.open()
    return store


class TestSchema:
    def test_schema_created(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()
        tables = [
            row[0]
            for row in store._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        assert "telemetry_executions" in tables
        assert "telemetry_usage" in tables
        assert "telemetry_costs" in tables
        store.close()

    def test_schema_idempotent(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()
        store.close()
        store.open()
        assert store.is_open()
        store.close()


class TestInsertExecution:
    def test_insert_and_query(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()

        event = {
            "execution_id": "exec-001",
            "event_id": "evt-001",
            "correlation_id": "corr-001",
            "task_id": "task-001",
            "agent": "planner",
            "model": "gpt-4o",
            "provider": "openai",
            "attempt": 1,
            "status": "succeeded",
            "duration_ms": 1200.0,
            "timestamp": "2026-01-01T00:00:00Z",
        }
        store.insert_execution(event)

        rows = store.query_executions(agent="planner")
        assert len(rows) == 1
        assert rows[0]["execution_id"] == "exec-001"
        assert rows[0]["agent"] == "planner"
        store.close()

    def test_insert_duplicate_event_id_ignored(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()

        event = {
            "execution_id": "exec-001",
            "event_id": "evt-001",
            "agent": "planner",
            "status": "running",
            "timestamp": "2026-01-01T00:00:00Z",
        }
        store.insert_execution(event)
        store.insert_execution(event)  # duplicate event_id

        rows = store.query_executions(agent="planner")
        assert len(rows) == 1
        store.close()

    def test_project_isolation(self, tmp_path):
        db = tmp_path / "test.db"
        store_a = TelemetryStore(db, "project-a")
        store_b = TelemetryStore(db, "project-b")
        store_a.open()
        store_b.open()

        store_a.insert_execution(
            {
                "execution_id": "exec-a",
                "event_id": "evt-a",
                "agent": "planner",
                "status": "succeeded",
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )
        store_b.insert_execution(
            {
                "execution_id": "exec-b",
                "event_id": "evt-b",
                "agent": "developer",
                "status": "succeeded",
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )

        assert len(store_a.query_executions()) == 1
        assert len(store_b.query_executions()) == 1
        assert store_a.query_executions()[0]["execution_id"] == "exec-a"
        assert store_b.query_executions()[0]["execution_id"] == "exec-b"

        store_a.close()
        store_b.close()


class TestInsertUsage:
    def test_insert_and_query(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()

        usage = {
            "execution_id": "exec-001",
            "agent": "planner",
            "model": "gpt-4o",
            "provider": "openai",
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "cached_tokens": 10,
            "reasoning_tokens": None,
            "context_tokens": None,
            "provider_raw": {"foo": "bar"},
            "timestamp": "2026-01-01T00:00:00Z",
        }
        store.insert_usage(usage)

        rows = store.query_usage(agent="planner")
        assert len(rows) == 1
        assert rows[0]["input_tokens"] == 100
        assert rows[0]["output_tokens"] == 50
        assert rows[0]["model"] == "gpt-4o"
        store.close()

    def test_filter_by_model(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()

        store.insert_usage(
            {
                "execution_id": "exec-a",
                "agent": "planner",
                "model": "gpt-4o",
                "input_tokens": 10,
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )
        store.insert_usage(
            {
                "execution_id": "exec-b",
                "agent": "developer",
                "model": "claude",
                "input_tokens": 20,
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )

        rows_gpt = store.query_usage(model="gpt-4o")
        assert len(rows_gpt) == 1

        rows_claude = store.query_usage(model="claude")
        assert len(rows_claude) == 1
        store.close()

    def test_filter_by_date_range(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()

        store.insert_usage(
            {
                "execution_id": "exec-1",
                "agent": "planner",
                "input_tokens": 10,
                "timestamp": "2026-01-01T10:00:00Z",
            }
        )
        store.insert_usage(
            {
                "execution_id": "exec-2",
                "agent": "developer",
                "input_tokens": 20,
                "timestamp": "2026-01-02T10:00:00Z",
            }
        )

        rows = store.query_usage(date_from="2026-01-02T00:00:00Z")
        assert len(rows) == 1
        assert rows[0]["execution_id"] == "exec-2"
        store.close()


class TestInsertCost:
    def test_insert_and_query(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()

        cost = {
            "execution_id": "exec-001",
            "pricing_version": "v1",
            "pricing_source": "builtin",
            "input_cost": 0.0005,
            "output_cost": 0.0008,
            "total_cost": 0.0013,
            "status": "priced",
            "calculated_at": "2026-01-01T00:00:00Z",
        }
        store.insert_cost(cost)

        rows = store.query_costs()
        assert len(rows) == 1
        assert rows[0]["status"] == "priced"
        assert rows[0]["total_cost"] == 0.0013
        assert rows[0]["pricing_source"] == "builtin"
        store.close()


class TestAggregateUsage:
    def test_aggregates_correctly(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()

        store.insert_usage(
            {
                "execution_id": "exec-1",
                "agent": "planner",
                "model": "gpt-4o",
                "input_tokens": 100,
                "output_tokens": 50,
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )
        store.insert_usage(
            {
                "execution_id": "exec-2",
                "agent": "developer",
                "model": "gpt-4o",
                "input_tokens": 200,
                "output_tokens": 100,
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )
        store.insert_cost(
            {
                "execution_id": "exec-1",
                "pricing_version": "v1",
                "total_cost": 0.001,
                "status": "priced",
                "calculated_at": "2026-01-01T00:00:00Z",
            }
        )
        store.insert_cost(
            {
                "execution_id": "exec-2",
                "pricing_version": "v1",
                "total_cost": 0.002,
                "status": "priced",
                "calculated_at": "2026-01-01T00:00:00Z",
            }
        )

        agg = store.aggregate_usage()
        assert agg["totals"]["input_tokens"] == 300
        assert agg["totals"]["output_tokens"] == 150
        assert agg["totals"]["total_cost"] == 0.003
        assert len(agg["by_agent"]) == 2
        assert agg["by_agent"]["planner"]["input_tokens"] == 100
        assert agg["by_agent"]["developer"]["input_tokens"] == 200
        assert len(agg["by_model"]) == 1
        assert agg["by_model"]["gpt-4o"]["input_tokens"] == 300
        store.close()

    def test_aggregate_includes_executions_when_tokens_deferred(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()

        store.insert_execution(
            {
                "execution_id": "exec-1",
                "event_id": "evt-1",
                "agent": "planner",
                "status": "succeeded",
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )
        store.insert_execution(
            {
                "execution_id": "exec-2",
                "event_id": "evt-2",
                "agent": "developer",
                "status": "succeeded",
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )

        agg = store.aggregate_usage()
        assert agg["totals"]["input_tokens"] == 0
        assert agg["records"] == []
        assert len(agg["executions"]) == 2
        assert agg["total_executions"] == 2
        assert agg["total_records"] == 0
        assert {e["agent"] for e in agg["executions"]} == {"planner", "developer"}
        store.close()

    def test_aggregate_reports_totals_when_limit_truncates(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()

        for i in range(5):
            store.insert_execution(
                {
                    "execution_id": f"exec-{i}",
                    "event_id": f"evt-{i}",
                    "agent": "planner",
                    "status": "succeeded",
                    "timestamp": "2026-01-01T00:00:00Z",
                }
            )

        agg = store.aggregate_usage(limit=2)
        assert len(agg["executions"]) == 2
        assert agg["total_executions"] == 5

        store.close()


class TestTelemetryStoreClosed:
    def test_query_on_closed_store(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()
        store.close()
        assert store.query_usage() == []
        assert store.query_costs() == []
        assert store.query_executions() == []
        assert store.query_retrieval() == []
        assert store.query_skill_stats() == []
        assert store.query_gate_stats() == []
        assert store.query_gate_records() == []
        assert store.query_security_stats() == []
        assert store.query_security_records() == []
        assert store.query_routing_stats() == []
        assert store.query_routing_records() == []
        assert store.query_route_accuracy() == []
        assert store.query_backlog_stats() == []

    def test_atomic_on_closed_store_raises(self, tmp_path):
        store = TelemetryStore(tmp_path / "test.db", "project-1")
        with pytest.raises(TelemetryError):
            store.atomic()

    def test_insert_many_on_closed_store_raises(self, tmp_path):
        store = TelemetryStore(tmp_path / "test.db", "project-1")
        with pytest.raises(TelemetryError):
            store.insert_many("usage", [{"agent": "planner"}])

    def test_insert_many_unknown_table_raises(self, tmp_path):
        store = _open_store(tmp_path)
        with pytest.raises(TelemetryError):
            store.insert_many("nonexistent", [{}])
        store.close()

    def test_insert_one_is_noop_on_closed_store(self, tmp_path):
        store = TelemetryStore(tmp_path / "test.db", "project-1")
        store.insert_usage({"agent": "planner"})  # should not raise
        store.insert_retrieval({})
        store.insert_skill_usage({})
        store.insert_gate_record({})
        store.insert_security_decision({})
        store.insert_routing({})
        store.insert_backlog_run({})


class TestAtomic:
    def test_atomic_commits_on_success(self, tmp_path):
        store = _open_store(tmp_path)
        with store.atomic():
            store.insert_many(
                "usage",
                [
                    {"execution_id": "e1", "agent": "planner", "input_tokens": 1},
                    {"execution_id": "e2", "agent": "planner", "input_tokens": 2},
                ],
            )
        assert len(store.query_usage()) == 2
        store.close()

    def test_insert_many_inserts_rows(self, tmp_path):
        store = _open_store(tmp_path)
        with store.atomic():
            store.insert_many(
                "usage",
                [{"execution_id": "e1", "agent": "planner", "input_tokens": 5}],
            )
        assert store.query_usage()[0]["input_tokens"] == 5
        store.close()

    def test_insert_many_failure_raises(self, tmp_path, monkeypatch):
        store = _open_store(tmp_path)

        def _boom(*args, **kwargs):
            raise sqlite3.Error("constraint failed")

        monkeypatch.setattr(store._conn, "executemany", _boom)
        with pytest.raises(sqlite3.Error):
            store.insert_many("usage", [{"agent": "planner"}])
        store.close()


class TestOpenErrors:
    def test_open_directory_not_creatable_raises(self, tmp_path, monkeypatch):
        store = TelemetryStore(tmp_path / "x" / "test.db", "project-1")

        def _boom(self, *args, **kwargs):
            raise OSError("permission denied")

        monkeypatch.setattr("pathlib.Path.mkdir", _boom)
        with pytest.raises(TelemetryError):
            store.open()

    def test_open_sqlite_error_raises(self, tmp_path):
        store = TelemetryStore(tmp_path / "test.db", "project-1")
        store.open()  # fine
        # simulate a failure during a *second* fresh open on a corrupt file
        corrupt = tmp_path / "corrupt.db"
        corrupt.write_text("not a database")
        bad = TelemetryStore(corrupt, "project-1")
        with pytest.raises(TelemetryError):
            bad.open()

    def test_open_injected_connection(self, tmp_path):
        conn = connect_threadsafe(tmp_path / "shared.db")
        store = TelemetryStore(tmp_path / "unused.db", "project-1", connection=conn)
        store.open()
        assert store.is_open()
        store.insert_many("usage", [{"execution_id": "e1", "agent": "planner"}])
        conn.commit()
        assert len(store.query_usage()) == 1
        store.close()  # releases the reference only
        assert store._conn is None

    def test_close_injected_connection_releases_reference(self, tmp_path):
        conn = connect_threadsafe(tmp_path / "shared.db")
        store = TelemetryStore(tmp_path / "unused.db", "project-1", connection=conn)
        store.open()
        store.close()
        assert store._conn is None
        conn.close()

    def test_is_open_false_when_closed(self, tmp_path):
        store = TelemetryStore(tmp_path / "test.db", "project-1")
        assert store.is_open() is False

    def test_is_open_false_when_connection_broken(self, tmp_path):
        store = _open_store(tmp_path)
        store._conn._conn.close()  # close the underlying sqlite connection
        assert store.is_open() is False
        store._conn = None


class TestRetrieval:
    def test_insert_and_query(self, tmp_path):
        store = _open_store(tmp_path)
        store.insert_retrieval(
            {
                "agent": "developer",
                "query": "find routes",
                "chunks_retrieved": 10,
                "chunks_selected": 3,
                "retriever": "vector",
                "compression_ratio": 0.7,
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )
        rows = store.query_retrieval(agent="developer")
        assert len(rows) == 1
        assert rows[0]["query"] == "find routes"
        assert rows[0]["chunks_retrieved"] == 10
        assert rows[0]["retriever"] == "vector"
        store.close()

    def test_query_retrieval_no_agent_filter(self, tmp_path):
        store = _open_store(tmp_path)
        store.insert_retrieval({"agent": "developer", "query": "q"})
        assert len(store.query_retrieval()) == 1
        store.close()


class TestSkills:
    def test_insert_and_query_stats(self, tmp_path):
        store = _open_store(tmp_path)
        store.insert_skill_usage(
            {
                "skill_name": "coding-style",
                "agent": "developer",
                "considered": 1,
                "selected": 1,
                "used": 1,
                "relevance_score": 0.9,
                "tokens_contributed": 120,
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )
        rows = store.query_skill_stats(skill="coding-style")
        assert len(rows) == 1
        assert rows[0]["skill_name"] == "coding-style"
        assert rows[0]["total_used"] == 1
        assert rows[0]["total_tokens"] == 120
        store.close()

    def test_query_skill_stats_agent_and_date_filter(self, tmp_path):
        store = _open_store(tmp_path)
        store.insert_skill_usage(
            {
                "skill_name": "s",
                "agent": "developer",
                "used": 1,
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )
        assert len(store.query_skill_stats(agent="developer")) == 1
        assert len(store.query_skill_stats(agent="planner")) == 0
        assert len(store.query_skill_stats(date_from="2026-01-02T00:00:00Z")) == 0
        assert len(store.query_skill_stats(date_to="2026-01-02T00:00:00Z")) == 1
        store.close()


class TestGates:
    def test_insert_and_query_records(self, tmp_path):
        store = _open_store(tmp_path)
        store.insert_gate_record(
            {
                "gate": "code_gate",
                "status": "passed",
                "blocked": False,
                "duration_ms": 12.5,
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )
        rows = store.query_gate_records(gate="code_gate")
        assert len(rows) == 1
        assert rows[0]["status"] == "passed"
        assert rows[0]["blocked"] == 0
        store.close()

    def test_insert_and_query_stats(self, tmp_path):
        store = _open_store(tmp_path)
        store.insert_gate_record(
            {
                "gate": "code_gate",
                "status": "passed",
                "findings_high": 1,
                "blocked": False,
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )
        stats = store.query_gate_stats(gate="code_gate")
        assert len(stats) == 1
        assert stats[0]["gate"] == "code_gate"
        assert stats[0]["passed"] == 1
        assert stats[0]["findings_high"] == 1
        store.close()

    def test_query_gate_stats_status_filter(self, tmp_path):
        store = _open_store(tmp_path)
        store.insert_gate_record({"gate": "g", "status": "failed"})
        store.insert_gate_record({"gate": "g2", "status": "passed"})
        assert len(store.query_gate_stats(status="failed")) == 1
        assert len(store.query_gate_records(status="passed")) == 1
        store.close()


class TestSecurity:
    def test_insert_and_query_records(self, tmp_path):
        store = _open_store(tmp_path)
        store.insert_security_decision(
            {
                "decision": "allow",
                "agent": "planner",
                "action": "read",
                "allowed": True,
                "reason": "ok",
                "violations": ["v1"],
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )
        rows = store.query_security_records(decision="allow")
        assert len(rows) == 1
        assert rows[0]["allowed"] == 1
        assert rows[0]["violations"] == ["v1"]
        store.close()

    def test_query_security_stats(self, tmp_path):
        store = _open_store(tmp_path)
        store.insert_security_decision({"decision": "allow", "allowed": True})
        store.insert_security_decision({"decision": "deny", "allowed": False})
        stats = store.query_security_stats()
        by_decision = {s["decision"]: s for s in stats}
        assert by_decision["allow"]["allowed"] == 1
        assert by_decision["deny"]["denied"] == 1
        assert len(store.query_security_stats(decision="deny")) == 1
        store.close()

    def test_query_security_records_allowed_filter(self, tmp_path):
        store = _open_store(tmp_path)
        store.insert_security_decision({"decision": "allow", "allowed": True})
        store.insert_security_decision({"decision": "deny", "allowed": False})
        assert len(store.query_security_records(allowed=True)) == 1
        assert len(store.query_security_records(allowed=False)) == 1
        store.close()

    def test_security_violations_string_passthrough(self, tmp_path):
        store = _open_store(tmp_path)
        store.insert_security_decision({"decision": "d", "violations": '["a", "b"]'})
        rows = store.query_security_records()
        assert rows[0]["violations"] == ["a", "b"]
        store.close()


class TestRouting:
    def test_insert_and_query_records(self, tmp_path):
        store = _open_store(tmp_path)
        store.insert_routing(
            {
                "agent": "developer",
                "model": "gpt-4o",
                "provider": "openai",
                "task_type": "code",
                "fallback_used": False,
                "estimated_cost": 0.012,
                "correlation_id": "corr-1",
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )
        rows = store.query_routing_records(agent="developer")
        assert len(rows) == 1
        assert rows[0]["fallback_used"] is False
        store.close()

    def test_query_routing_stats(self, tmp_path):
        store = _open_store(tmp_path)
        store.insert_routing(
            {
                "agent": "developer",
                "model": "gpt-4o",
                "provider": "openai",
                "fallback_used": True,
                "estimated_cost": 0.1,
                "context_size": 1000,
            }
        )
        stats = store.query_routing_stats(agent="developer")
        assert len(stats) == 1
        assert stats[0]["fallbacks"] == 1
        assert stats[0]["routes"] == 1
        store.close()

    def test_query_route_accuracy(self, tmp_path):
        store = _open_store(tmp_path)
        store.insert_routing(
            {
                "agent": "developer",
                "model": "gpt-4o",
                "estimated_cost": 0.05,
                "correlation_id": "corr-1",
            }
        )
        store.insert_execution(
            {
                "execution_id": "e1",
                "event_id": "evt-1",
                "correlation_id": "corr-1",
                "agent": "developer",
                "model": "gpt-4o",
                "status": "succeeded",
            }
        )
        store.insert_cost(
            {
                "execution_id": "e1",
                "pricing_version": "v1",
                "total_cost": 0.07,
                "status": "priced",
            }
        )
        rows = store.query_route_accuracy()
        assert len(rows) == 1
        assert rows[0]["actual_cost"] == 0.07
        assert rows[0]["delta"] == 0.02
        store.close()

    def test_query_route_accuracy_empty_without_costs(self, tmp_path):
        store = _open_store(tmp_path)
        store.insert_routing({"agent": "developer", "model": "gpt-4o"})
        assert store.query_route_accuracy() == []
        store.close()


class TestBacklog:
    def test_insert_and_query(self, tmp_path):
        store = _open_store(tmp_path)
        store.insert_backlog_run(
            {
                "run_id": "r1",
                "task_index": 0,
                "task_title": "add models",
                "task_type": "feat",
                "status": "succeeded",
                "duration_ms": 10.0,
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )
        rows = store.query_backlog_stats(status="succeeded")
        assert len(rows) == 1
        assert rows[0]["task_title"] == "add models"
        assert rows[0]["task_type"] == "feat"
        store.close()

    def test_query_backlog_run_id_filter(self, tmp_path):
        store = _open_store(tmp_path)
        store.insert_backlog_run({"run_id": "r1", "status": "failed"})
        store.insert_backlog_run({"run_id": "r2", "status": "succeeded"})
        assert len(store.query_backlog_stats(run_id="r1")) == 1
        assert len(store.query_backlog_stats(status="failed")) == 1
        store.close()


class TestQueryErrorHandling:
    def test_query_usage_sql_error_returns_empty(self, tmp_path, monkeypatch):
        store = _open_store(tmp_path)
        monkeypatch.setattr(
            store._conn,
            "execute",
            lambda *a, **k: (_ for _ in ()).throw(sqlite3.Error("boom")),
        )
        assert store.query_usage() == []
        assert store.query_costs() == []
        assert store.query_executions() == []
        assert store.query_retrieval() == []
        assert store.query_skill_stats() == []
        assert store.query_gate_stats() == []
        assert store.query_gate_records() == []
        assert store.query_security_stats() == []
        assert store.query_security_records() == []
        assert store.query_routing_stats() == []
        assert store.query_routing_records() == []
        assert store.query_route_accuracy() == []
        assert store.query_backlog_stats() == []
        store.close()


class TestAggregateFilters:
    def test_aggregate_usage_with_workflow_id_filters(self, tmp_path):
        store = _open_store(tmp_path)
        store.insert_execution(
            {
                "execution_id": "e1",
                "event_id": "evt-1",
                "agent": "planner",
                "workflow_id": "wf-1",
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )
        store.insert_usage(
            {
                "execution_id": "e1",
                "agent": "planner",
                "model": "gpt-4o",
                "input_tokens": 10,
                "total_tokens": 10,
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )
        agg = store.aggregate_usage(workflow_id="wf-1")
        # executions are filtered by workflow_id directly
        assert agg["total_executions"] == 1
        assert agg["totals"]["total_tokens"] == 10

        agg_no_match = store.aggregate_usage(workflow_id="wf-other")
        assert agg_no_match["total_executions"] == 0
        store.close()

    def test_aggregate_usage_with_agent_and_model_filters(self, tmp_path):
        store = _open_store(tmp_path)
        store.insert_usage(
            {
                "execution_id": "e1",
                "agent": "planner",
                "model": "gpt-4o",
                "input_tokens": 10,
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )
        store.insert_usage(
            {
                "execution_id": "e2",
                "agent": "developer",
                "model": "claude",
                "input_tokens": 20,
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )
        agg = store.aggregate_usage(agent="planner", model="gpt-4o")
        assert agg["totals"]["input_tokens"] == 10
        assert agg["total_records"] == 1
        store.close()

    def test_aggregate_usage_date_filters(self, tmp_path):
        store = _open_store(tmp_path)
        store.insert_execution(
            {
                "execution_id": "e1",
                "event_id": "evt-1",
                "agent": "planner",
                "timestamp": "2026-01-01T00:00:00Z",
            }
        )
        agg = store.aggregate_usage(
            date_from="2026-01-01T00:00:00Z", date_to="2026-01-02T00:00:00Z"
        )
        assert agg["total_executions"] == 1
        store.close()

    def test_aggregate_usage_total_tokens_falls_back_to_sum(self, tmp_path):
        store = _open_store(tmp_path)
        # total_tokens absent -> falls back to input + output
        store.insert_usage(
            {
                "execution_id": "e1",
                "agent": "planner",
                "input_tokens": 30,
                "output_tokens": 20,
            }
        )
        agg = store.aggregate_usage()
        assert agg["totals"]["total_tokens"] == 50
        store.close()


class TestInsertOneErrorHandling:
    def test_insert_one_logs_and_continues_on_error(self, tmp_path, monkeypatch):
        """_insert_one swallows sqlite errors (logs and returns) instead of raising."""
        store = _open_store(tmp_path)

        def _boom(*args, **kwargs):
            raise sqlite3.Error("boom")

        monkeypatch.setattr(store._conn, "execute", _boom)
        store.insert_usage({"agent": "planner"})  # must not raise
        store.close()


class TestCountErrorHandling:
    def test_count_returns_zero_on_sql_error(self, tmp_path, monkeypatch):
        store = _open_store(tmp_path)
        monkeypatch.setattr(
            store._conn,
            "execute",
            lambda *a, **k: (_ for _ in ()).throw(sqlite3.Error("boom")),
        )
        assert store._count("telemetry_usage", ["project_id = ?"], ["p"]) == 0
        store.close()

    def test_count_returns_zero_when_closed(self):
        store = TelemetryStore(Path("/tmp/x.db"), "p")
        assert store._count("telemetry_usage", ["project_id = ?"], ["p"]) == 0


class TestOpenInjectedError:
    def test_open_injected_sqlite_error_raises(self, tmp_path):
        conn = connect_threadsafe(tmp_path / "shared.db")
        conn.close()  # force executescript to fail on a closed connection
        store = TelemetryStore(tmp_path / "unused.db", "project-1", connection=conn)
        with pytest.raises(TelemetryError):
            store.open()


class TestDateFilters:
    def test_query_gate_stats_date_filters(self, tmp_path):
        store = _open_store(tmp_path)
        store.insert_gate_record(
            {"gate": "g", "status": "passed", "timestamp": "2026-01-01T00:00:00Z"}
        )
        assert len(store.query_gate_stats(date_from="2026-01-02T00:00:00Z")) == 0
        assert len(store.query_gate_stats(date_to="2026-01-02T00:00:00Z")) == 1
        assert len(store.query_gate_records(date_from="2026-01-02T00:00:00Z")) == 0
        assert len(store.query_gate_records(date_to="2026-01-02T00:00:00Z")) == 1
        store.close()

    def test_query_security_date_and_agent_filters(self, tmp_path):
        store = _open_store(tmp_path)
        store.insert_security_decision(
            {"decision": "d", "agent": "planner", "timestamp": "2026-01-01T00:00:00Z"}
        )
        assert len(store.query_security_stats(date_from="2026-01-02T00:00:00Z")) == 0
        assert len(store.query_security_stats(date_to="2026-01-02T00:00:00Z")) == 1
        assert len(store.query_security_stats(agent="planner")) == 1
        assert len(store.query_security_stats(agent="developer")) == 0
        assert len(store.query_security_records(agent="planner")) == 1
        assert len(store.query_security_records(agent="developer")) == 0
        assert len(store.query_security_records(date_from="2026-01-02T00:00:00Z")) == 0
        assert len(store.query_security_records(date_to="2026-01-02T00:00:00Z")) == 1
        store.close()

    def test_query_routing_date_and_model_filters(self, tmp_path):
        store = _open_store(tmp_path)
        store.insert_routing(
            {"agent": "developer", "model": "gpt-4o", "timestamp": "2026-01-01T00:00:00Z"}
        )
        assert len(store.query_routing_stats(model="gpt-4o")) == 1
        assert len(store.query_routing_stats(model="claude")) == 0
        assert len(store.query_routing_stats(date_from="2026-01-02T00:00:00Z")) == 0
        assert len(store.query_routing_stats(date_to="2026-01-02T00:00:00Z")) == 1
        assert len(store.query_routing_records(model="gpt-4o")) == 1
        assert len(store.query_routing_records(model="claude")) == 0
        assert len(store.query_routing_records(date_from="2026-01-02T00:00:00Z")) == 0
        assert len(store.query_routing_records(date_to="2026-01-02T00:00:00Z")) == 1
        store.close()

    def test_query_backlog_date_filters(self, tmp_path):
        store = _open_store(tmp_path)
        store.insert_backlog_run(
            {"run_id": "r1", "status": "succeeded", "timestamp": "2026-01-01T00:00:00Z"}
        )
        assert len(store.query_backlog_stats(date_from="2026-01-02T00:00:00Z")) == 0
        assert len(store.query_backlog_stats(date_to="2026-01-02T00:00:00Z")) == 1
        store.close()
