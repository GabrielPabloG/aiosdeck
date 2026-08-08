"""End-to-end test: real kernel wiring order for routing telemetry.

Replicates the exact startup order used by Kernel.start():
  1. EventsEngine.initialize() → creates EventBus
  2. TelemetryEngine.initialize() → store + subscribe (bus NOT yet wired)
  3. RuntimeEngine.initialize() → adapter init
  4. _wire_event_bus(): runtime.set_event_bus(bus),
     telemetry.set_event_bus(bus) → re-subscription
  5. Execute → routing event → persisted in telemetry_routing
"""

from __future__ import annotations

import json
from pathlib import Path

from aios.config.schema import RouteConfig
from aios.events import EventsEngine
from aios.routing.engine import RuleBasedRouter


class FakeAdapter:
    name = "fake"
    version = "1.0"
    calls: list[dict]

    def __init__(self):
        self.calls = []

    def initialize(self):
        pass

    def health_check(self):
        return True

    def shutdown(self):
        pass

    @property
    def command(self):
        return "fake"

    @property
    def has_sandbox(self):
        return False

    def execute(  # noqa: PLR0913
        self, prompt, skills, capabilities=None, permissions=None, *, model="", variant=""
    ):
        self.calls.append({"model": model, "variant": variant})
        return json.dumps({"ok": True, "model": model})


def test_kernel_wiring_order_persists_routing(tmp_path: Path):
    from aios.agents.developer import DeveloperAgent  # noqa: F401

    from aios.runtime import RuntimeEngine
    from aios.telemetry.engine import TelemetryEngine

    db = tmp_path / "test.db"

    events = EventsEngine()

    adapter = FakeAdapter()
    config = RouteConfig(
        rules=[{"agent": "planner", "provider": "ollama", "model": "llama3:70b"}],
        fallback_providers=[{"provider": "ollama", "model": "llama3"}],
    )
    router = RuleBasedRouter(config)
    runtime = RuntimeEngine(adapter=adapter, router=router)

    telemetry = TelemetryEngine(project_path=tmp_path, db_path=str(db))

    events.initialize()
    bus = events.bus
    runtime.initialize()
    telemetry.initialize()

    runtime.set_event_bus(bus)
    telemetry.set_event_bus(bus)

    runtime.execute(
        "prompt",
        [],
        agent="planner",
        task_type="plan",
        complexity="high",
    )

    records = telemetry.query_routing_records()
    assert len(records) >= 1, f"expected ≥1 routing record, got {records}"
    r = records[0]
    assert r["agent"] == "planner"
    assert r["model"] == "ollama/llama3:70b"
    assert r["reason"] == "policy:0"

    stats = telemetry.query_routing_stats(agent="planner")
    assert len(stats) >= 1
    assert stats[0]["agent"] == "planner"

    telemetry.shutdown()
