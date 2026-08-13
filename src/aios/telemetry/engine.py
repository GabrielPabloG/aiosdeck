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

from aios.storage.pool import ConnectionPool
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

    def __init__(
        self,
        project_path: Path | None = None,
        db_path: str | None = None,
        connection_pool: ConnectionPool | None = None,
    ) -> None:
        self._project_path = project_path or Path.cwd()
        self._project_id = self._project_path.resolve().as_posix()
        self._db_path = db_path or str(self._project_path / ".aios" / "memory.db")
        self._store: TelemetryStore | None = None
        self._bus: EventBus | None = None
        self._pricing = PricingResolver(version="v1")
        self._subscription_count = 0
        self._connection_pool = connection_pool

    def set_event_bus(self, bus: EventBus) -> None:
        self._bus = bus
        if bus is not None and self._store is not None:
            self._subscribe()

    def initialize(self) -> None:
        connection = None
        if self._connection_pool is not None:
            connection = self._connection_pool.get(self._db_path)
        self._store = TelemetryStore(Path(self._db_path), self._project_id, connection=connection)
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

    def query(  # noqa: PLR0913 - filters are the telemetry audit contract
        self,
        *,
        agent: str | None = None,
        model: str | None = None,
        workflow_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 10000,
    ) -> dict:
        if self._store is None:
            return {
                "totals": {},
                "by_agent": {},
                "by_model": {},
                "records": [],
                "cost_records": [],
                "executions": [],
                "total_records": 0,
                "total_executions": 0,
            }
        return self._store.aggregate_usage(
            agent=agent,
            model=model,
            workflow_id=workflow_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )

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

    def query_security_stats(
        self,
        *,
        decision: str | None = None,
        agent: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        if self._store is None:
            return []
        return self._store.query_security_stats(
            decision=decision,
            agent=agent,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )

    def query_security_records(  # noqa: PLR0913 - filters are the audit contract
        self,
        *,
        decision: str | None = None,
        agent: str | None = None,
        allowed: bool | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        if self._store is None:
            return []
        return self._store.query_security_records(
            decision=decision,
            agent=agent,
            allowed=allowed,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )

    # ------------------------------------------------------------------
    # EventBus subscriptions
    # ------------------------------------------------------------------

    def _subscribe(self) -> None:
        if self._bus is None or self._subscription_count > 0:
            return
        self._bus.subscribe("agent.lifecycle.changed", self._on_lifecycle_event)
        self._bus.subscribe("agent.execution.*", self._on_execution_event)
        self._bus.subscribe("quality.*", self._on_gate_event)
        self._bus.subscribe("security.*", self._on_security_event)
        self._bus.subscribe("runtime.route_selected", self._on_routing_event)
        self._bus.subscribe("backlog.*", self._on_backlog_event)
        self._subscription_count += 6

    def _unsubscribe(self) -> None:
        if self._bus is None or self._subscription_count == 0:
            return
        self._bus.unsubscribe("agent.lifecycle.changed", self._on_lifecycle_event)
        self._bus.unsubscribe("agent.execution.*", self._on_execution_event)
        self._bus.unsubscribe("quality.*", self._on_gate_event)
        self._bus.unsubscribe("security.*", self._on_security_event)
        self._bus.unsubscribe("runtime.route_selected", self._on_routing_event)
        self._bus.unsubscribe("backlog.*", self._on_backlog_event)
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

    def _on_security_event(self, event) -> None:
        if self._store is None:
            return
        payload = event.payload if hasattr(event, "payload") else event
        if not isinstance(payload, dict):
            return
        record = {
            "decision": payload.get("decision", ""),
            "agent": payload.get("agent", ""),
            "action": payload.get("action", ""),
            "allowed": bool(payload.get("allowed")),
            "reason": payload.get("reason", ""),
            "violations": payload.get("violations", []),
            "intent_source": payload.get("intent_source", ""),
            "correlation_id": payload.get("correlation_id")
            or (getattr(event, "correlation_id", "") or ""),
            "timestamp": payload.get("timestamp", _now()),
        }
        self._store.insert_security_decision(record)

    def _on_routing_event(self, event) -> None:
        if self._store is None:
            return
        payload = event.payload if hasattr(event, "payload") else event
        if not isinstance(payload, dict):
            return
        record = {
            "agent": payload.get("agent", ""),
            "task_type": payload.get("task_type", ""),
            "complexity": payload.get("complexity", ""),
            "provider": payload.get("provider", ""),
            "model": payload.get("model", ""),
            "variant": payload.get("variant", ""),
            "reason": payload.get("reason", ""),
            "estimated_cost": payload.get("estimated_cost", 0.0),
            "context_size": payload.get("context_size", 0),
            "source": payload.get("source", ""),
            "fallback_used": bool(payload.get("fallback_used")),
            "fallback_reason": payload.get("fallback_reason", ""),
            "correlation_id": payload.get("correlation_id")
            or (getattr(event, "correlation_id", "") or ""),
            "timestamp": payload.get("timestamp", _now()),
        }
        self._store.insert_routing(record)

    def query_routing_stats(
        self,
        *,
        agent: str | None = None,
        model: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        if self._store is None:
            return []
        return self._store.query_routing_stats(
            agent=agent, model=model, date_from=date_from, date_to=date_to, limit=limit
        )

    def query_routing_records(
        self,
        *,
        agent: str | None = None,
        model: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        if self._store is None:
            return []
        return self._store.query_routing_records(
            agent=agent, model=model, date_from=date_from, date_to=date_to, limit=limit
        )

    def query_route_accuracy(self, *, limit: int = 100) -> list[dict]:
        if self._store is None:
            return []
        return self._store.query_route_accuracy(limit=limit)

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

    # ------------------------------------------------------------------
    # Backlog event handlers
    # ------------------------------------------------------------------

    def _on_backlog_event(self, event) -> None:
        if self._store is None:
            return
        payload = event.payload if hasattr(event, "payload") else event
        if not isinstance(payload, dict):
            return
        record = {
            "run_id": payload.get("run_id", ""),
            "task_index": payload.get("task_index", 0),
            "task_title": payload.get("task_title", ""),
            "task_type": payload.get("task_type", ""),
            "task_scope": payload.get("task_scope", ""),
            "status": payload.get("status", ""),
            "commit_sha": payload.get("commit_sha", ""),
            "duration_ms": payload.get("duration_ms"),
            "error": payload.get("error", ""),
            "source": payload.get("source", ""),
            "timestamp": payload.get("timestamp", _now()),
        }
        self._store.insert_backlog_run(record)

    def query_backlog_stats(
        self,
        *,
        run_id: str | None = None,
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        if self._store is None:
            return []
        return self._store.query_backlog_stats(
            run_id=run_id,
            status=status,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
