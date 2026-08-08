"""Tests for routing telemetry — event recording and queries."""

import tempfile
from pathlib import Path

import pytest

from aios.telemetry.store import TelemetryStore, _now
from aios.events.events import RUNTIME_ROUTE_SELECTED


class TestRoutingTelemetry:
    def test_routing_table_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            store = TelemetryStore(db_path, "test-project")
            store.open()
            try:
                rows = store._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='telemetry_routing'"
                ).fetchall()
                assert len(rows) == 1
            finally:
                store.close()

    def test_insert_and_query_routing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            store = TelemetryStore(db_path, "test-project")
            store.open()
            try:
                store.insert_routing(
                    {
                        "agent": "planner",
                        "task_type": "plan",
                        "complexity": "high",
                        "provider": "anthropic",
                        "model": "claude-sonnet",
                        "variant": "high",
                        "reason": "policy:0",
                        "estimated_cost": 0.15,
                        "context_size": 12000,
                        "source": "router",
                        "fallback_used": False,
                        "fallback_reason": "",
                        "correlation_id": "corr-1",
                    }
                )

                store.insert_routing(
                    {
                        "agent": "developer",
                        "task_type": "code",
                        "complexity": "medium",
                        "provider": "ollama",
                        "model": "llama3",
                        "variant": "",
                        "reason": "heuristic:default",
                        "estimated_cost": 0.0,
                        "context_size": 4000,
                        "source": "router",
                        "fallback_used": True,
                        "fallback_reason": "unavailable",
                        "correlation_id": "corr-2",
                    }
                )

                stats = store.query_routing_stats(agent="planner")
                assert len(stats) >= 1
                planner_stat = [s for s in stats if s["agent"] == "planner"][0]
                assert planner_stat["routes"] == 1

                records = store.query_routing_records(limit=10)
                assert len(records) == 2

                dev_records = store.query_routing_records(agent="developer")
                assert len(dev_records) == 1
                assert dev_records[0]["fallback_used"] is True
            finally:
                store.close()

    def test_route_accuracy_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            store = TelemetryStore(db_path, "test-project")
            store.open()
            try:
                store.insert_routing(
                    {
                        "agent": "planner",
                        "task_type": "plan",
                        "complexity": "high",
                        "provider": "anthropic",
                        "model": "claude-sonnet",
                        "variant": "",
                        "reason": "policy:0",
                        "estimated_cost": 0.15,
                        "context_size": 12000,
                        "correlation_id": "corr-acc-1",
                    }
                )

                store._conn.execute(
                    """INSERT INTO telemetry_executions
                       (execution_id, event_id, correlation_id, agent, model, status, timestamp, project_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        "exec-1",
                        "evt-1",
                        "corr-acc-1",
                        "planner",
                        "claude-sonnet",
                        "succeeded",
                        _now(),
                        "test-project",
                    ),
                )
                store._conn.execute(
                    """INSERT INTO telemetry_costs
                       (execution_id, total_cost, status, calculated_at, project_id)
                       VALUES (?, ?, ?, ?, ?)""",
                    ("exec-1", 0.18, "priced", _now(), "test-project"),
                )
                store._conn.commit()

                accuracy = store.query_route_accuracy()
                assert len(accuracy) >= 1
                row = accuracy[0]
                assert row["agent"] == "planner"
                assert row["estimated_cost"] == 0.15
                assert row["actual_cost"] == 0.18
                assert row["delta"] == pytest.approx(0.03, abs=0.01)
            finally:
                store.close()

    def test_routing_stats_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            store = TelemetryStore(db_path, "test-project")
            store.open()
            try:
                store.insert_routing(
                    {
                        "agent": "planner",
                        "model": "claude-sonnet",
                        "provider": "anthropic",
                    }
                )
                store.insert_routing(
                    {
                        "agent": "developer",
                        "model": "llama3",
                        "provider": "ollama",
                    }
                )

                stats_all = store.query_routing_stats()
                assert len(stats_all) >= 2

                stats_planner = store.query_routing_stats(agent="planner")
                assert len(stats_planner) == 1
                assert stats_planner[0]["agent"] == "planner"

                stats_model = store.query_routing_stats(model="llama3")
                assert len(stats_model) == 1
                assert stats_model[0]["model"] == "llama3"
            finally:
                store.close()


class TestRoutingEventConstant:
    def test_route_selected_in_runtime_topics(self):
        from aios.events.events import RUNTIME_TOPICS

        assert "runtime.route_selected" in RUNTIME_TOPICS

    def test_route_selected_in_all_topics(self):
        from aios.events.events import ALL_TOPICS

        assert "runtime.route_selected" in ALL_TOPICS

    def test_route_selected_constant(self):
        assert RUNTIME_ROUTE_SELECTED == "runtime.route_selected"
