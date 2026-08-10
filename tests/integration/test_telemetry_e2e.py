"""End-to-end tests for telemetry pipeline: executor → events → store → query."""

from aios.agents.contracts import (
    AgentCapabilities,
    AgentMetadata,
    AgentTask,
    RetryPolicy,
)
from aios.agents.executor import AgentExecutor, make_request
from aios.agents.models import AgentResult
from aios.events.bus import EventBus
from aios.telemetry.engine import TelemetryEngine
from aios.usage.models import UsageRecord


class _FakeAgent:
    name = "fake"

    def __init__(self, fn=None, usage=None):
        self._fn = fn or (lambda task, context: AgentResult(success=True, output="ok"))
        self._usage = usage
        self.metadata = AgentMetadata(name=self.name, retry_policy=RetryPolicy())
        self.capabilities = AgentCapabilities.from_list(["filesystem_read"])

    def execute(self, task, context):
        result = self._fn(task, context)
        if self._usage:
            result.usage = self._usage
        return result


def _task():
    return AgentTask(description="do something")


def test_e2e_execution_persisted(tmp_path):
    db = tmp_path / "test.db"
    bus = EventBus()
    executor = AgentExecutor(event_bus=bus)

    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.set_event_bus(bus)
    engine.initialize()

    outcome = executor.execute(make_request(_FakeAgent(), _task()))
    assert outcome.status == "succeeded"

    rows = engine._store.query_executions()
    assert len(rows) >= 2


def test_e2e_usage_persisted(tmp_path):
    db = tmp_path / "test.db"
    bus = EventBus()
    executor = AgentExecutor(event_bus=bus)

    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.set_event_bus(bus)
    engine.initialize()

    usage = UsageRecord(
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        model="gpt-4o",
        provider="openai",
        agent="fake",
    )
    outcome = executor.execute(make_request(_FakeAgent(usage=usage), _task()))
    assert outcome.status == "succeeded"

    result = engine.query()
    assert result["totals"]["input_tokens"] == 100
    assert result["totals"]["output_tokens"] == 50

    cost_rows = result["cost_records"]
    assert len(cost_rows) >= 1
    assert cost_rows[0]["status"] == "priced"

    engine.shutdown()


def test_e2e_multiple_executions_aggregated(tmp_path):
    db = tmp_path / "test.db"
    bus = EventBus()
    executor = AgentExecutor(event_bus=bus)

    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.set_event_bus(bus)
    engine.initialize()

    u1 = UsageRecord(
        input_tokens=100, output_tokens=50, model="gpt-4o", provider="openai", agent="fake"
    )
    u2 = UsageRecord(
        input_tokens=200, output_tokens=100, model="gpt-4o", provider="openai", agent="fake"
    )
    u3 = UsageRecord(
        input_tokens=300, output_tokens=150, model="gpt-4o", provider="openai", agent="developer"
    )

    executor.execute(make_request(_FakeAgent(usage=u1), _task()))
    executor.execute(make_request(_FakeAgent(usage=u2), _task()))

    fake_dev = _FakeAgent(usage=u3)
    fake_dev.name = "developer"
    executor.execute(make_request(fake_dev, _task()))

    result = engine.query()
    assert result["totals"]["input_tokens"] == 600
    assert result["totals"]["output_tokens"] == 300
    assert len(result["by_agent"]) == 2

    engine.shutdown()


def test_e2e_unpriced_provider(tmp_path):
    db = tmp_path / "test.db"
    bus = EventBus()
    executor = AgentExecutor(event_bus=bus)

    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.set_event_bus(bus)
    engine.initialize()

    usage = UsageRecord(
        input_tokens=100,
        output_tokens=50,
        model="unknown-model",
        provider="unknown-provider",
        agent="fake",
    )
    executor.execute(make_request(_FakeAgent(usage=usage), _task()))

    result = engine.query()
    cost_rows = result["cost_records"]
    assert len(cost_rows) >= 1
    assert cost_rows[0]["status"] == "unpriced"

    engine.shutdown()


def test_e2e_execution_without_usage_no_usage_record(tmp_path):
    db = tmp_path / "test.db"
    bus = EventBus()
    executor = AgentExecutor(event_bus=bus)

    engine = TelemetryEngine(project_path=tmp_path, db_path=str(db))
    engine.set_event_bus(bus)
    engine.initialize()

    executor.execute(make_request(_FakeAgent(), _task()))

    result = engine.query()
    assert result["totals"]["input_tokens"] == 0
    assert len(result["records"]) == 0
    assert len(result["executions"]) >= 2

    engine.shutdown()
