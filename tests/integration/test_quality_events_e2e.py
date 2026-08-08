"""End-to-end tests: quality.* events → EventBus → TelemetryEngine → store."""

from aios.events.bus import EventBus
from aios.events.events import ALL_TOPICS
from aios.telemetry.engine import TelemetryEngine


def _engine(tmp_path):
    db = tmp_path / "test.db"
    bus = EventBus()
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.set_event_bus(bus)
    engine.initialize()
    return bus, engine


def test_all_gate_topics_registered():
    for topic in (
        "quality.started",
        "quality.gate_started",
        "quality.gate_completed",
        "quality.gate_blocked",
        "quality.gate_passed",
        "quality.gate_failed",
        "quality.completed",
    ):
        assert topic in ALL_TOPICS


def test_publishing_gate_topic_does_not_warn(tmp_path, caplog):
    bus, engine = _engine(tmp_path)
    with caplog.at_level("WARNING", logger="aios.events"):
        bus.publish("quality.gate_started", {"gate": "code_gate"})
    assert not any("Unknown topic" in r.message for r in caplog.records)
    engine.shutdown()


def test_e2e_gate_passed_persisted(tmp_path):
    bus, engine = _engine(tmp_path)
    bus.publish(
        "quality.gate_passed",
        {
            "gate": "code_gate",
            "status": "passed",
            "duration_ms": 12.5,
            "findings": {"low": 0, "medium": 0, "high": 0, "critical": 0},
            "blocked": False,
            "overridden": False,
        },
        correlation_id="run-1",
    )
    stats = engine.query_gate_stats(gate="code_gate")
    assert len(stats) == 1
    assert stats[0]["passed"] == 1
    assert stats[0]["blocked"] == 0
    engine.shutdown()


def test_e2e_gate_failed_with_block_decision(tmp_path):
    bus, engine = _engine(tmp_path)
    bus.publish(
        "quality.gate_failed",
        {
            "gate": "security_gate",
            "status": "failed",
            "duration_ms": 3.0,
            "findings": {"low": 0, "medium": 1, "high": 2, "critical": 1},
            "blocked": True,
            "overridden": False,
        },
        correlation_id="run-2",
    )
    stats = engine.query_gate_stats(gate="security_gate")
    assert stats[0]["failed"] == 1
    assert stats[0]["blocked"] == 1
    assert stats[0]["findings_high"] == 2
    assert stats[0]["findings_critical"] == 1
    engine.shutdown()


def test_e2e_status_derived_from_topic_and_correlation_id(tmp_path):
    bus, engine = _engine(tmp_path)
    bus.publish(
        "quality.gate_blocked",
        {"gate": "code_gate", "blocked": True, "overridden": False},
        correlation_id="run-3",
    )
    rows = engine.query_gate_records(gate="code_gate")
    assert len(rows) == 1
    assert rows[0]["status"] == "blocked"
    assert rows[0]["correlation_id"] == "run-3"
    assert rows[0]["blocked"] == 1
    engine.shutdown()


def test_e2e_lifecycle_topics_produce_no_records(tmp_path):
    bus, engine = _engine(tmp_path)
    bus.publish("quality.started", {"correlation_id": "run-4"})
    bus.publish("quality.gate_started", {"gate": "code_gate"})
    bus.publish("quality.completed", {"correlation_id": "run-4"})
    assert engine.query_gate_records() == []
    engine.shutdown()


def test_e2e_overridden_gate_recorded(tmp_path):
    bus, engine = _engine(tmp_path)
    bus.publish(
        "quality.gate_failed",
        {
            "gate": "code_gate",
            "status": "failed",
            "blocked": True,
            "overridden": True,
            "findings": {"high": 1},
        },
        correlation_id="run-5",
    )
    rows = engine.query_gate_records(gate="code_gate")
    assert rows[0]["overridden"] == 1
    assert rows[0]["findings_high"] == 1
    engine.shutdown()
