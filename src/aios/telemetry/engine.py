"""TelemetryEngine — observes execution events and persists telemetry.

Subscribes to ``agent.lifecycle.changed`` and ``agent.execution.*`` topics
via the EventBus. For every event, it persists an execution record. When a
``completed`` event carries a ``usage`` payload, it persists a normalized
``UsageRecord`` and calculates cost via ``PricingResolver``.

The engine is a passive observer — it never interferes with execution.
Agents, the executor, and the event bus work identically with or without
telemetry.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from aios.telemetry.pricing import PricingResolver
from aios.telemetry.store import TelemetryStore, _now

if TYPE_CHECKING:
    from aios.events.bus import EventBus

logger = logging.getLogger("aios.telemetry")

_GATE_TOPIC_STATUS = {
    "quality.gate_passed": "passed",
    "quality.gate_failed": "failed",
    "quality.gate_blocked": "blocked",
    "quality.gate_completed": "completed",
}


class TelemetryEngine:
    name = "telemetry"

    def __init__(self, project_path: Path | None = None, db_path: str | None = None) -> None:
        self._project_path = project_path or Path.cwd()
        self._project_id = self._project_path.resolve().as_posix()
        self._db_path = db_path or str(self._project_path / ".aios" / "memory.db")
        self._store: TelemetryStore | None = None
        self._bus: EventBus | None = None
        self._pricing = PricingResolver(version="v1")
        self._subscription_count = 0

    def set_event_bus(self, bus: EventBus) -> None:
        self._bus = bus

    def initialize(self) -> None:
        self._store = TelemetryStore(Path(self._db_path), self._project_id)
        self._store.open()
        self._subscribe()

    def health_check(self) -> bool:
        if self._store is None:
            return True
        return self._store.is_open()

    def shutdown(self) -> None:
        self._unsubscribe()
        if self._store:
            self._store.close()
            self._store = None

    def query(self, **filters) -> dict:
        if self._store is None:
            return {"totals": {}, "by_agent": {}, "by_model": {}, "records": [], "cost_records": []}
        return self._store.aggregate_usage(**filters)

    def record_retrieval(self, metrics: dict) -> None:
        if self._store is None:
            return
        self._store.insert_retrieval(metrics)

    def query_retrieval(self, *, agent: str | None = None, limit: int = 100) -> list[dict]:
        if self._store is None:
            return []
        return self._store.query_retrieval(agent=agent, limit=limit)

    def record_skill_usage(self, record: dict) -> None:
        if self._store is None:
            return
        self._store.insert_skill_usage(record)

    def query_skill_stats(
        self,
        *,
        skill: str | None = None,
        agent: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        if self._store is None:
            return []
        return self._store.query_skill_stats(
            skill=skill,
            agent=agent,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )

    def query_gate_stats(
        self,
        *,
        gate: str | None = None,
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        if self._store is None:
            return []
        return self._store.query_gate_stats(
            gate=gate,
            status=status,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )

    def query_gate_records(
        self,
        *,
        gate: str | None = None,
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        if self._store is None:
            return []
        return self._store.query_gate_records(
            gate=gate,
            status=status,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )

    # ------------------------------------------------------------------
    # EventBus subscriptions
    # ------------------------------------------------------------------

    def _subscribe(self) -> None:
        if self._bus is None:
            return
        self._bus.subscribe("agent.lifecycle.changed", self._on_lifecycle_event)
        self._bus.subscribe("agent.execution.*", self._on_execution_event)
        self._bus.subscribe("quality.*", self._on_gate_event)
        self._subscription_count += 3

    def _unsubscribe(self) -> None:
        if self._bus is None:
            return
        self._bus.unsubscribe("agent.lifecycle.changed", self._on_lifecycle_event)
        self._bus.unsubscribe("agent.execution.*", self._on_execution_event)
        self._bus.unsubscribe("quality.*", self._on_gate_event)
        self._subscription_count = 0

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_lifecycle_event(self, event) -> None:
        self._persist_execution(event)

    def _on_execution_event(self, event) -> None:
        self._persist_execution(event)

        payload = event.payload if hasattr(event, "payload") else event
        if isinstance(payload, dict) and payload.get("status") == "succeeded":
            usage = payload.get("usage")
            if (
                usage
                and isinstance(usage, dict)
                and any(
                    usage.get(k) is not None
                    for k in ("input_tokens", "output_tokens", "total_tokens")
                )
            ):
                self._persist_usage(usage, payload)
                self._persist_cost(usage, payload)

    def _on_gate_event(self, event) -> None:
        if self._store is None:
            return
        payload = event.payload if hasattr(event, "payload") else event
        if not isinstance(payload, dict):
            return
        topic = event.topic if hasattr(event, "topic") else ""
        status = payload.get("status") or _GATE_TOPIC_STATUS.get(topic)
        if status is None:
            return
        findings = payload.get("findings")
        if not isinstance(findings, dict):
            findings = {}
        record = {
            "gate": payload.get("gate", ""),
            "status": str(status),
            "correlation_id": payload.get("correlation_id")
            or (getattr(event, "correlation_id", "") or ""),
            "duration_ms": payload.get("duration_ms"),
            "findings_low": int(findings.get("low", payload.get("findings_low", 0)) or 0),
            "findings_medium": int(findings.get("medium", payload.get("findings_medium", 0)) or 0),
            "findings_high": int(findings.get("high", payload.get("findings_high", 0)) or 0),
            "findings_critical": int(
                findings.get("critical", payload.get("findings_critical", 0)) or 0
            ),
            "blocked": bool(payload.get("blocked")),
            "overridden": bool(payload.get("overridden")),
            "timestamp": payload.get("timestamp", _now()),
        }
        self._store.insert_gate_record(record)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _persist_execution(self, event) -> None:
        if self._store is None:
            return
        payload = event.payload if hasattr(event, "payload") else event
        if not isinstance(payload, dict):
            return
        record = {
            "execution_id": payload.get("execution_id", ""),
            "event_id": payload.get("event_id", str(hash(str(payload)))),
            "correlation_id": payload.get("correlation_id", ""),
            "task_id": payload.get("task_id", ""),
            "workflow_id": payload.get("workflow_id"),
            "agent": payload.get("agent", ""),
            "model": payload.get("model"),
            "provider": payload.get("provider"),
            "runtime": payload.get("runtime"),
            "attempt": payload.get("attempt", 1),
            "status": payload.get("status", ""),
            "duration_ms": payload.get("duration_ms"),
            "timestamp": payload.get("timestamp", _now()),
        }
        self._store.insert_execution(record)

    def _persist_usage(self, usage: dict, event_payload: dict) -> None:
        if self._store is None:
            return
        record = {
            "execution_id": event_payload.get("execution_id", ""),
            "agent": event_payload.get("agent", ""),
            "model": usage.get("model", ""),
            "provider": usage.get("provider", ""),
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "cached_tokens": usage.get("cached_tokens"),
            "reasoning_tokens": usage.get("reasoning_tokens"),
            "context_tokens": usage.get("context_tokens"),
            "provider_raw": usage.get("provider_raw"),
            "timestamp": usage.get("timestamp", _now()),
        }
        if not record["total_tokens"] and record["input_tokens"] and record["output_tokens"]:
            record["total_tokens"] = record["input_tokens"] + record["output_tokens"]
        self._store.insert_usage(record)

    def _persist_cost(self, usage: dict, event_payload: dict) -> None:
        if self._store is None:
            return
        provider = usage.get("provider", "")
        model = usage.get("model", "")
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")

        cost = self._pricing.resolve(provider, model, input_tokens, output_tokens)
        cost["execution_id"] = event_payload.get("execution_id", "")
        self._store.insert_cost(cost)
