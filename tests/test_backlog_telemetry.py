"""Tests for backlog telemetry — insert_backlog_run and query_backlog_stats."""

from pathlib import Path

from aios.events.events import (
    BACKLOG_RUN_COMPLETED,
    BACKLOG_RUN_STARTED,
    BACKLOG_TASK_FAILED,
    BACKLOG_TASK_STARTED,
    BACKLOG_TASK_SUCCEEDED,
    BACKLOG_TOPICS,
    ALL_TOPICS,
)


def test_backlog_topics_in_all_topics() -> None:
    for topic in BACKLOG_TOPICS:
        assert topic in ALL_TOPICS, f"{topic} missing from ALL_TOPICS"


def test_backlog_topic_constants_match_lists() -> None:
    assert BACKLOG_RUN_STARTED in BACKLOG_TOPICS
    assert BACKLOG_TASK_STARTED in BACKLOG_TOPICS
    assert BACKLOG_TASK_SUCCEEDED in BACKLOG_TOPICS
    assert BACKLOG_TASK_FAILED in BACKLOG_TOPICS
    assert BACKLOG_RUN_COMPLETED in BACKLOG_TOPICS


class TestBacklogStore:
    def test_insert_and_query(self, tmp_path: Path) -> None:
        from aios.telemetry.store import TelemetryStore

        db = tmp_path / "test.db"
        store = TelemetryStore(db, "test_project")
        store.open()

        store.insert_backlog_run(
            {
                "run_id": "run-1",
                "task_index": 0,
                "task_title": "feat(backlog): add models",
                "task_type": "feat",
                "task_scope": "backlog",
                "status": "succeeded",
                "commit_sha": "abc123",
                "duration_ms": 1500.0,
                "error": "",
                "source": "file:TODO.md",
            }
        )
        store.insert_backlog_run(
            {
                "run_id": "run-1",
                "task_index": 1,
                "task_title": "fix(core): handle null",
                "task_type": "fix",
                "task_scope": "core",
                "status": "failed",
                "commit_sha": "",
                "duration_ms": 500.0,
                "error": "something broke",
                "source": "file:TODO.md",
            }
        )

        all_runs = store.query_backlog_stats()
        assert len(all_runs) == 2
        assert all_runs[0]["task_title"] == "fix(core): handle null"
        assert all_runs[1]["task_title"] == "feat(backlog): add models"

        succeeded = store.query_backlog_stats(status="succeeded")
        assert len(succeeded) == 1
        assert succeeded[0]["commit_sha"] == "abc123"

        by_run = store.query_backlog_stats(run_id="run-1")
        assert len(by_run) == 2

        store.close()

    def test_empty_when_no_records(self, tmp_path: Path) -> None:
        from aios.telemetry.store import TelemetryStore

        db = tmp_path / "test.db"
        store = TelemetryStore(db, "test_project")
        store.open()
        assert store.query_backlog_stats() == []
        store.close()

    def test_store_not_open_returns_empty(self) -> None:
        from aios.telemetry.store import TelemetryStore

        store = TelemetryStore(Path("/nonexistent/test.db"), "test")
        assert store.query_backlog_stats() == []


class TestBacklogEngine:
    def test_query_delegates_to_store(self, tmp_path: Path) -> None:
        from aios.telemetry.engine import TelemetryEngine

        engine = TelemetryEngine(project_path=tmp_path, db_path=str(tmp_path / "test.db"))
        engine.initialize()

        stats = engine.query_backlog_stats()
        assert stats == []

        engine.shutdown()

    def test_insert_through_event_bus(self, tmp_path: Path) -> None:
        from aios.events.bus import EventBus
        from aios.telemetry.engine import TelemetryEngine

        engine = TelemetryEngine(project_path=tmp_path, db_path=str(tmp_path / "test.db"))
        engine.initialize()
        bus = EventBus()
        engine.set_event_bus(bus)

        bus.publish(
            BACKLOG_TASK_SUCCEEDED,
            {
                "run_id": "run-1",
                "task_index": 0,
                "task_title": "feat: test",
                "task_type": "feat",
                "task_scope": "",
                "status": "succeeded",
                "commit_sha": "def456",
                "duration_ms": 100.0,
                "error": "",
                "source": "test",
            },
        )

        stats = engine.query_backlog_stats()
        assert len(stats) == 1
        assert stats[0]["commit_sha"] == "def456"

        engine.shutdown()
