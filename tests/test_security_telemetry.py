"""Tests for security audit events and the queryable telemetry trail.

The executor publishes ``security.intent.applied`` plus ``security.check.passed``
or ``security.check.denied`` only when an intent is present (opt-in — zero
events without an intent). ``TelemetryEngine`` persists them into the additive
``telemetry_security`` table; the audit trail is a query, not a raw log.
"""

from aios.agents.contracts import (
    STATE_FAILED,
    STATE_SUCCEEDED,
    AgentCapabilities,
    AgentMetadata,
    AgentTask,
    RetryPolicy,
)
from aios.agents.executor import AgentExecutor, make_request
from aios.agents.models import AgentResult
from aios.events.bus import EventBus
from aios.events.events import (
    SECURITY_CHECK_DENIED,
    SECURITY_CHECK_PASSED,
    SECURITY_INTENT_APPLIED,
    SECURITY_TOPICS,
    ALL_TOPICS,
)
from aios.security.actions import (
    FILESYSTEM_READ_ACTION,
    GIT_BRANCH,
    GIT_COMMIT,
)
from aios.security import IntentPolicy
from aios.telemetry.engine import TelemetryEngine
from aios.telemetry.store import TelemetryStore


class _GitAgent:
    name = "git"

    def __init__(self):
        self.metadata = AgentMetadata(name=self.name, retry_policy=RetryPolicy())
        self.capabilities = AgentCapabilities.from_list(["git"])

    def execute(self, task, context):
        return AgentResult(success=True, output="ok")


def _task() -> AgentTask:
    return AgentTask(description="do something")


def _engine(tmp_path):
    db = tmp_path / "test.db"
    bus = EventBus()
    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.set_event_bus(bus)
    engine.initialize()
    return bus, engine


class TestSecuritySchema:
    def test_security_table_created(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()
        tables = [
            row[0]
            for row in store._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        assert "telemetry_security" in tables
        store.close()

    def test_security_schema_idempotent(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()
        store.close()
        store.open()
        assert store.is_open()
        store.close()


class TestSecurityTelemetryStore:
    def test_insert_and_query_stats(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()
        store.insert_security_decision(
            {
                "decision": "check.denied",
                "agent": "git",
                "action": "review",
                "allowed": False,
                "reason": "no overlap",
                "violations": ["git.branch", "git.commit"],
                "intent_source": "default",
                "correlation_id": "run-1",
            }
        )
        stats = store.query_security_stats()
        assert len(stats) == 1
        assert stats[0]["decision"] == "check.denied"
        assert stats[0]["denied"] == 1
        store.close()

    def test_stats_aggregate_allowed_and_denied(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()
        store.insert_security_decision({"decision": "check.passed", "allowed": True})
        store.insert_security_decision({"decision": "check.denied", "allowed": False})
        store.insert_security_decision({"decision": "check.denied", "allowed": False})
        stats = store.query_security_stats()
        assert {s["decision"] for s in stats} == {"check.passed", "check.denied"}
        by_name = {s["decision"]: s for s in stats}
        assert by_name["check.passed"]["allowed"] == 1
        assert by_name["check.denied"]["denied"] == 2
        store.close()

    def test_query_records_round_trip_violations_json(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()
        store.insert_security_decision(
            {
                "decision": "check.denied",
                "agent": "git",
                "allowed": False,
                "violations": ["git.branch", "git.commit"],
                "intent_source": "default",
            }
        )
        rows = store.query_security_records()
        assert len(rows) == 1
        assert rows[0]["decision"] == "check.denied"
        assert rows[0]["agent"] == "git"
        assert rows[0]["violations"] == ["git.branch", "git.commit"]
        assert rows[0]["intent_source"] == "default"
        store.close()

    def test_project_isolation(self, tmp_path):
        db = tmp_path / "test.db"
        store_a = TelemetryStore(db, "project-a")
        store_b = TelemetryStore(db, "project-b")
        store_a.open()
        store_b.open()
        store_a.insert_security_decision({"decision": "check.denied", "allowed": False})
        store_b.insert_security_decision({"decision": "check.passed", "allowed": True})
        assert len(store_a.query_security_records()) == 1
        assert len(store_b.query_security_records()) == 1
        assert store_a.query_security_records()[0]["decision"] == "check.denied"
        store_a.close()
        store_b.close()

    def test_queries_on_closed_store(self, tmp_path):
        db = tmp_path / "test.db"
        store = TelemetryStore(db, "project-1")
        store.open()
        store.close()
        assert store.query_security_stats() == []
        assert store.query_security_records() == []


class TestSecurityTopicsRegistered:
    def test_topics_in_all_topics(self):
        for topic in (SECURITY_INTENT_APPLIED, SECURITY_CHECK_PASSED, SECURITY_CHECK_DENIED):
            assert topic in ALL_TOPICS
            assert topic in SECURITY_TOPICS

    def test_publishing_security_topic_does_not_warn(self, tmp_path, caplog):
        bus, engine = _engine(tmp_path)
        with caplog.at_level("WARNING", logger="aios.events"):
            bus.publish(SECURITY_CHECK_DENIED, {"decision": "check.denied", "allowed": False})
        assert not any("Unknown topic" in r.message for r in caplog.records)
        engine.shutdown()


class TestExecutorSecurityEvents:
    def test_no_intent_emits_no_security_events(self, tmp_path):
        bus, engine = _engine(tmp_path)
        executor = AgentExecutor(event_bus=bus)
        executor.execute(make_request(_GitAgent(), _task()))
        assert engine.query_security_records() == []
        engine.shutdown()

    def test_denied_run_emits_applied_and_denied(self, tmp_path):
        bus, engine = _engine(tmp_path)
        executor = AgentExecutor(event_bus=bus)
        intent = IntentPolicy(name="review", actions=frozenset({FILESYSTEM_READ_ACTION}))
        outcome = executor.execute(make_request(_GitAgent(), _task(), intent=intent))
        assert outcome.status == STATE_FAILED
        rows = engine.query_security_records()
        decisions = {r["decision"] for r in rows}
        assert decisions == {SECURITY_INTENT_APPLIED, SECURITY_CHECK_DENIED}
        denied = next(r for r in rows if r["decision"] == SECURITY_CHECK_DENIED)
        assert denied["agent"] == "git"
        assert denied["allowed"] == 0
        assert denied["violations"] == ["git.branch", "git.commit"]
        assert denied["intent_source"] == "default"
        engine.shutdown()

    def test_allowed_run_emits_applied_and_passed(self, tmp_path):
        bus, engine = _engine(tmp_path)
        executor = AgentExecutor(event_bus=bus)
        intent = IntentPolicy(actions=frozenset({GIT_BRANCH, GIT_COMMIT}))
        outcome = executor.execute(make_request(_GitAgent(), _task(), intent=intent))
        assert outcome.status == STATE_SUCCEEDED
        rows = engine.query_security_records()
        decisions = {r["decision"] for r in rows}
        assert decisions == {SECURITY_INTENT_APPLIED, SECURITY_CHECK_PASSED}
        passed = next(r for r in rows if r["decision"] == SECURITY_CHECK_PASSED)
        assert passed["allowed"] == 1
        engine.shutdown()
