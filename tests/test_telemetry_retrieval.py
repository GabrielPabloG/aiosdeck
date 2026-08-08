"""Tests for telemetry_retrieval table — persistence and query of retrieval metrics."""

from aios.telemetry.engine import TelemetryEngine
from aios.telemetry.store import TelemetryStore


class TestTelemetryRetrieval:
    def test_table_exists(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()

        tables = [
            row[0]
            for row in store._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        assert "telemetry_retrieval" in tables
        store.close()

    def test_insert_and_query(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()

        store.insert_retrieval(
            {
                "agent": "planner",
                "query": "test query",
                "chunks_retrieved": 20,
                "chunks_selected": 5,
                "tokens_before": 400,
                "tokens_after": 120,
                "compression_ratio": 0.7,
                "retrieval_latency_ms": 12.5,
                "retriever": "keyword",
            }
        )

        records = store.query_retrieval(agent="planner", limit=10)
        assert len(records) == 1
        r = records[0]
        assert r["agent"] == "planner"
        assert r["chunks_retrieved"] == 20
        assert r["chunks_selected"] == 5
        assert r["tokens_before"] == 400
        assert r["tokens_after"] == 120
        assert abs(r["compression_ratio"] - 0.7) < 0.001
        assert abs(r["retrieval_latency_ms"] - 12.5) < 0.01

        store.close()

    def test_query_multiple_agents(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()

        store.insert_retrieval({"agent": "planner", "query": "q1", "compression_ratio": 0.5})
        store.insert_retrieval({"agent": "research", "query": "q2", "compression_ratio": 0.8})
        store.insert_retrieval({"agent": "planner", "query": "q3", "compression_ratio": 0.3})

        planner = store.query_retrieval(agent="planner", limit=10)
        assert len(planner) == 2

        all_records = store.query_retrieval(limit=10)
        assert len(all_records) == 3

        store.close()

    def test_compression_ratio_formula(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()

        before, after = 500, 100
        ratio = 1.0 - (after / before)
        assert abs(ratio - 0.8) < 0.001

        store.insert_retrieval(
            {
                "agent": "test",
                "query": "compression test",
                "tokens_before": before,
                "tokens_after": after,
                "compression_ratio": ratio,
            }
        )

        records = store.query_retrieval(limit=1)
        assert abs(records[0]["compression_ratio"] - 0.8) < 0.001

        store.close()

    def test_project_isolation(self, tmp_path):
        db = tmp_path / "test.db"
        store_a = TelemetryStore(db, "project-a")
        store_b = TelemetryStore(db, "project-b")
        store_a.open()
        store_b.open()

        store_a.insert_retrieval({"agent": "planner", "query": "qa", "compression_ratio": 0.5})
        store_b.insert_retrieval({"agent": "research", "query": "qb", "compression_ratio": 0.8})

        assert len(store_a.query_retrieval()) == 1
        assert len(store_b.query_retrieval()) == 1
        assert store_a.query_retrieval()[0]["agent"] == "planner"
        assert store_b.query_retrieval()[0]["agent"] == "research"

        store_a.close()
        store_b.close()

    def test_engine_record_retrieval(self, tmp_path):
        db = tmp_path / "test.db"
        engine = TelemetryEngine(db_path=str(db))
        engine.initialize()

        engine.record_retrieval(
            {
                "agent": "planner",
                "query": "test",
                "chunks_retrieved": 20,
                "chunks_selected": 3,
                "tokens_before": 300,
                "tokens_after": 90,
                "compression_ratio": 0.7,
                "retrieval_latency_ms": 5.0,
                "retriever": "keyword",
            }
        )

        data = engine.query_retrieval(agent="planner")
        assert len(data) == 1
        assert data[0]["compression_ratio"] == 0.7

        engine.shutdown()
