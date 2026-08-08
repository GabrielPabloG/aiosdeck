"""Tests for TelemetryStore — schema, CRUD, isolation."""

from aios.telemetry.store import TelemetryStore


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

        store_a.insert_execution({
            "execution_id": "exec-a", "event_id": "evt-a",
            "agent": "planner", "status": "succeeded",
            "timestamp": "2026-01-01T00:00:00Z",
        })
        store_b.insert_execution({
            "execution_id": "exec-b", "event_id": "evt-b",
            "agent": "developer", "status": "succeeded",
            "timestamp": "2026-01-01T00:00:00Z",
        })

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

        store.insert_usage({
            "execution_id": "exec-a", "agent": "planner", "model": "gpt-4o",
            "input_tokens": 10, "timestamp": "2026-01-01T00:00:00Z",
        })
        store.insert_usage({
            "execution_id": "exec-b", "agent": "developer", "model": "claude",
            "input_tokens": 20, "timestamp": "2026-01-01T00:00:00Z",
        })

        rows_gpt = store.query_usage(model="gpt-4o")
        assert len(rows_gpt) == 1

        rows_claude = store.query_usage(model="claude")
        assert len(rows_claude) == 1
        store.close()

    def test_filter_by_date_range(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()

        store.insert_usage({
            "execution_id": "exec-1", "agent": "planner",
            "input_tokens": 10, "timestamp": "2026-01-01T10:00:00Z",
        })
        store.insert_usage({
            "execution_id": "exec-2", "agent": "developer",
            "input_tokens": 20, "timestamp": "2026-01-02T10:00:00Z",
        })

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

        store.insert_usage({
            "execution_id": "exec-1", "agent": "planner", "model": "gpt-4o",
            "input_tokens": 100, "output_tokens": 50,
            "timestamp": "2026-01-01T00:00:00Z",
        })
        store.insert_usage({
            "execution_id": "exec-2", "agent": "developer", "model": "gpt-4o",
            "input_tokens": 200, "output_tokens": 100,
            "timestamp": "2026-01-01T00:00:00Z",
        })
        store.insert_cost({
            "execution_id": "exec-1", "pricing_version": "v1",
            "total_cost": 0.001, "status": "priced",
            "calculated_at": "2026-01-01T00:00:00Z",
        })
        store.insert_cost({
            "execution_id": "exec-2", "pricing_version": "v1",
            "total_cost": 0.002, "status": "priced",
            "calculated_at": "2026-01-01T00:00:00Z",
        })

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


class TestTelemetryStoreClosed:
    def test_query_on_closed_store(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()
        store.close()
        assert store.query_usage() == []
        assert store.query_costs() == []
        assert store.query_executions() == []
