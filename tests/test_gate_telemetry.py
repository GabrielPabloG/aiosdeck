"""Tests for gate telemetry — schema, persistence, queries.

Covers the additive ``telemetry_gates`` table: per-severity findings,
block decision, overrides, project isolation, and both aggregate
(``query_gate_stats``) and record-level (``query_gate_records``) queries.
"""

from aios.telemetry.store import TelemetryStore


def _record(gate="code_gate", status="passed", **overrides):
    record = {
        "gate": gate,
        "status": status,
        "correlation_id": "run-1",
        "duration_ms": 120.0,
        "findings_low": 0,
        "findings_medium": 0,
        "findings_high": 0,
        "findings_critical": 0,
        "blocked": False,
        "overridden": False,
        "timestamp": "2026-01-01T00:00:00Z",
    }
    record.update(overrides)
    return record


class TestGateSchema:
    def test_gate_table_created(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()
        tables = [
            row[0]
            for row in store._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        assert "telemetry_gates" in tables
        store.close()

    def test_gate_schema_idempotent(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()
        store.close()
        store.open()
        assert store.is_open()
        store.close()


class TestInsertGateRecord:
    def test_insert_and_query_stats(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()
        store.insert_gate_record(_record())
        stats = store.query_gate_stats(gate="code_gate")
        assert len(stats) == 1
        assert stats[0]["gate"] == "code_gate"
        assert stats[0]["runs"] == 1
        assert stats[0]["passed"] == 1
        assert stats[0]["failed"] == 0
        assert stats[0]["blocked"] == 0
        store.close()

    def test_block_decision_and_status_aggregated(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()
        store.insert_gate_record(_record(status="failed", blocked=True))
        store.insert_gate_record(_record(status="passed"))
        stats = store.query_gate_stats(gate="code_gate")
        assert stats[0]["runs"] == 2
        assert stats[0]["passed"] == 1
        assert stats[0]["failed"] == 1
        assert stats[0]["blocked"] == 1
        store.close()

    def test_overridden_stored(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()
        store.insert_gate_record(_record(status="failed", blocked=True, overridden=True))
        stats = store.query_gate_stats(gate="code_gate")
        assert stats[0]["overridden"] == 1
        store.close()

    def test_findings_by_severity_aggregated(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()
        store.insert_gate_record(
            _record(gate="security_gate", findings_low=1, findings_medium=2, findings_high=3)
        )
        store.insert_gate_record(
            _record(gate="security_gate", findings_low=2, findings_medium=1, findings_critical=1)
        )
        stats = store.query_gate_stats(gate="security_gate")
        assert stats[0]["findings_low"] == 3
        assert stats[0]["findings_medium"] == 3
        assert stats[0]["findings_high"] == 3
        assert stats[0]["findings_critical"] == 1
        store.close()

    def test_filter_by_status(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()
        store.insert_gate_record(_record(status="passed"))
        store.insert_gate_record(_record(status="failed", blocked=True))
        stats = store.query_gate_stats(gate="code_gate", status="failed")
        assert len(stats) == 1
        assert stats[0]["failed"] == 1
        store.close()

    def test_query_records_round_trip(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()
        store.insert_gate_record(_record(gate="code_gate", status="passed"))
        rows = store.query_gate_records(gate="code_gate")
        assert len(rows) == 1
        assert rows[0]["gate"] == "code_gate"
        assert rows[0]["status"] == "passed"
        assert rows[0]["correlation_id"] == "run-1"
        assert rows[0]["duration_ms"] == 120.0
        assert rows[0]["blocked"] == 0
        store.close()

    def test_project_isolation(self, tmp_path):
        db = tmp_path / "test.db"
        store_a = TelemetryStore(db, "project-a")
        store_b = TelemetryStore(db, "project-b")
        store_a.open()
        store_b.open()
        store_a.insert_gate_record(_record(gate="code_gate"))
        store_b.insert_gate_record(_record(gate="security_gate"))
        assert len(store_a.query_gate_records()) == 1
        assert len(store_b.query_gate_records()) == 1
        assert store_a.query_gate_records()[0]["gate"] == "code_gate"
        assert store_b.query_gate_records()[0]["gate"] == "security_gate"
        store_a.close()
        store_b.close()


class TestGateStoreClosed:
    def test_queries_on_closed_store(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()
        store.close()
        assert store.query_gate_stats() == []
        assert store.query_gate_records() == []
