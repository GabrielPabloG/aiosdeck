"""SQLite storage backend for telemetry. Implementation detail of TelemetryEngine."""

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger("aios.telemetry.store")

SCHEMA = """
CREATE TABLE IF NOT EXISTS telemetry_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    correlation_id TEXT NOT NULL DEFAULT '',
    task_id TEXT NOT NULL DEFAULT '',
    workflow_id TEXT,
    agent TEXT NOT NULL,
    model TEXT,
    provider TEXT,
    runtime TEXT,
    attempt INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    duration_ms REAL,
    timestamp TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS telemetry_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT NOT NULL,
    agent TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT '',
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    cached_tokens INTEGER,
    reasoning_tokens INTEGER,
    context_tokens INTEGER,
    provider_raw TEXT,
    timestamp TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS telemetry_costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT NOT NULL,
    pricing_version TEXT NOT NULL DEFAULT '',
    pricing_source TEXT NOT NULL DEFAULT 'builtin',
    input_cost REAL NOT NULL DEFAULT 0,
    output_cost REAL NOT NULL DEFAULT 0,
    cached_cost REAL,
    reasoning_cost REAL,
    total_cost REAL NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'USD',
    status TEXT NOT NULL DEFAULT 'unpriced',
    calculated_at TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_te_execution_id ON telemetry_executions(execution_id);
CREATE INDEX IF NOT EXISTS idx_te_timestamp ON telemetry_executions(timestamp);
CREATE INDEX IF NOT EXISTS idx_te_agent ON telemetry_executions(agent);
CREATE INDEX IF NOT EXISTS idx_te_correlation ON telemetry_executions(correlation_id);
CREATE INDEX IF NOT EXISTS idx_te_workflow ON telemetry_executions(workflow_id);
CREATE INDEX IF NOT EXISTS idx_tu_execution ON telemetry_usage(execution_id);
CREATE INDEX IF NOT EXISTS idx_tu_timestamp ON telemetry_usage(timestamp);
CREATE INDEX IF NOT EXISTS idx_tu_agent ON telemetry_usage(agent);
CREATE INDEX IF NOT EXISTS idx_tu_model ON telemetry_usage(model);
CREATE INDEX IF NOT EXISTS idx_tc_execution ON telemetry_costs(execution_id);
"""


class TelemetryError(Exception):
    """Domain error for telemetry storage failures."""


class TelemetryStore:
    def __init__(self, db_path: Path, project_id: str) -> None:
        self._db_path = db_path
        self._project_id = project_id
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise TelemetryError(f"Cannot create directory: {self._db_path.parent}") from exc

        try:
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        except sqlite3.Error as exc:
            self._conn = None
            raise TelemetryError(f"Database open failed: {exc}") from exc

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def is_open(self) -> bool:
        if self._conn is None:
            return False
        try:
            self._conn.execute("SELECT 1")
            return True
        except sqlite3.Error:
            return False

    # ------------------------------------------------------------------
    # Execution records (event log)
    # ------------------------------------------------------------------

    def insert_execution(self, event: dict) -> None:
        if not self._conn:
            return
        try:
            self._conn.execute(
                """INSERT OR IGNORE INTO telemetry_executions
                   (execution_id, event_id, correlation_id, task_id, workflow_id,
                    agent, model, provider, runtime, attempt, status, duration_ms,
                    timestamp, project_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.get("execution_id", ""),
                    event.get("event_id", ""),
                    event.get("correlation_id", ""),
                    event.get("task_id", ""),
                    event.get("workflow_id"),
                    event.get("agent", ""),
                    event.get("model"),
                    event.get("provider"),
                    event.get("runtime"),
                    event.get("attempt", 1),
                    event.get("status", ""),
                    event.get("duration_ms"),
                    event.get("timestamp", _now()),
                    self._project_id,
                ),
            )
            self._conn.commit()
        except sqlite3.Error as exc:
            logger.warning("insert_execution failed: %s", exc)

    # ------------------------------------------------------------------
    # Usage records
    # ------------------------------------------------------------------

    def insert_usage(self, usage: dict) -> None:
        if not self._conn:
            return
        provider_raw_str = None
        if usage.get("provider_raw"):
            provider_raw_str = json.dumps(usage["provider_raw"], ensure_ascii=False)

        try:
            self._conn.execute(
                """INSERT INTO telemetry_usage
                   (execution_id, agent, model, provider,
                    input_tokens, output_tokens, total_tokens,
                    cached_tokens, reasoning_tokens, context_tokens,
                    provider_raw, timestamp, project_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    usage.get("execution_id", ""),
                    usage.get("agent", ""),
                    usage.get("model", ""),
                    usage.get("provider", ""),
                    usage.get("input_tokens"),
                    usage.get("output_tokens"),
                    usage.get("total_tokens"),
                    usage.get("cached_tokens"),
                    usage.get("reasoning_tokens"),
                    usage.get("context_tokens"),
                    provider_raw_str,
                    usage.get("timestamp", _now()),
                    self._project_id,
                ),
            )
            self._conn.commit()
        except sqlite3.Error as exc:
            logger.warning("insert_usage failed: %s", exc)

    # ------------------------------------------------------------------
    # Cost records
    # ------------------------------------------------------------------

    def insert_cost(self, cost: dict) -> None:
        if not self._conn:
            return
        try:
            self._conn.execute(
                """INSERT INTO telemetry_costs
                   (execution_id, pricing_version, pricing_source,
                    input_cost, output_cost, cached_cost, reasoning_cost,
                    total_cost, currency, status, calculated_at, project_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cost.get("execution_id", ""),
                    cost.get("pricing_version", ""),
                    cost.get("pricing_source", "builtin"),
                    cost.get("input_cost", 0.0),
                    cost.get("output_cost", 0.0),
                    cost.get("cached_cost"),
                    cost.get("reasoning_cost"),
                    cost.get("total_cost", 0.0),
                    cost.get("currency", "USD"),
                    cost.get("status", "unpriced"),
                    cost.get("calculated_at", _now()),
                    self._project_id,
                ),
            )
            self._conn.commit()
        except sqlite3.Error as exc:
            logger.warning("insert_cost failed: %s", exc)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def query_usage(  # noqa: PLR0913
        self,
        *,
        agent: str | None = None,
        model: str | None = None,
        workflow_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        if not self._conn:
            return []

        conditions = ["project_id = ?"]
        params: list = [self._project_id]

        if agent:
            conditions.append("agent = ?")
            params.append(agent)
        if model:
            conditions.append("model = ?")
            params.append(model)
        if workflow_id:
            conditions.append(
                "execution_id IN ("
                "SELECT execution_id FROM telemetry_executions "
                "WHERE workflow_id = ?)"
            )
            params.append(workflow_id)
        if date_from:
            conditions.append("timestamp >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("timestamp <= ?")
            params.append(date_to)

        where = " AND ".join(conditions)
        try:
            rows = self._conn.execute(
                f"SELECT execution_id, agent, model, provider, input_tokens, output_tokens, "
                f"total_tokens, cached_tokens, reasoning_tokens, context_tokens, "
                f"provider_raw, timestamp "
                f"FROM telemetry_usage "
                f"WHERE {where} "
                f"ORDER BY timestamp DESC "
                f"LIMIT ?",
                params + [limit],
            ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("query_usage failed: %s", exc)
            return []

        return [
            {
                "execution_id": row[0],
                "agent": row[1],
                "model": row[2],
                "provider": row[3],
                "input_tokens": row[4],
                "output_tokens": row[5],
                "total_tokens": row[6],
                "cached_tokens": row[7],
                "reasoning_tokens": row[8],
                "context_tokens": row[9],
                "provider_raw": row[10],
                "timestamp": row[11],
            }
            for row in rows
        ]

    def query_costs(  # noqa: PLR0913
        self,
        *,
        agent: str | None = None,
        model: str | None = None,
        workflow_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        if not self._conn:
            return []

        conditions = ["tc.project_id = ?"]
        params: list = [self._project_id]

        if agent:
            conditions.append(
                "tc.execution_id IN (SELECT execution_id FROM telemetry_usage WHERE agent = ?)"
            )
            params.append(agent)
        if model:
            conditions.append(
                "tc.execution_id IN (SELECT execution_id FROM telemetry_usage WHERE model = ?)"
            )
            params.append(model)
        if workflow_id:
            conditions.append(
                "tc.execution_id IN ("
                "SELECT execution_id FROM telemetry_executions "
                "WHERE workflow_id = ?)"
            )
            params.append(workflow_id)
        if date_from:
            conditions.append("tc.calculated_at >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("tc.calculated_at <= ?")
            params.append(date_to)

        where = " AND ".join(conditions)
        try:
            rows = self._conn.execute(
                f"SELECT tc.execution_id, tc.pricing_version, tc.pricing_source, "
                f"tc.input_cost, tc.output_cost, tc.cached_cost, tc.reasoning_cost, "
                f"tc.total_cost, tc.currency, tc.status, tc.calculated_at "
                f"FROM telemetry_costs tc "
                f"WHERE {where} "
                f"ORDER BY tc.calculated_at DESC "
                f"LIMIT ?",
                params + [limit],
            ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("query_costs failed: %s", exc)
            return []

        return [
            {
                "execution_id": row[0],
                "pricing_version": row[1],
                "pricing_source": row[2],
                "input_cost": row[3],
                "output_cost": row[4],
                "cached_cost": row[5],
                "reasoning_cost": row[6],
                "total_cost": row[7],
                "currency": row[8],
                "status": row[9],
                "calculated_at": row[10],
            }
            for row in rows
        ]

    def query_executions(
        self,
        *,
        agent: str | None = None,
        workflow_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        if not self._conn:
            return []

        conditions = ["project_id = ?"]
        params: list = [self._project_id]

        if agent:
            conditions.append("agent = ?")
            params.append(agent)
        if workflow_id:
            conditions.append("workflow_id = ?")
            params.append(workflow_id)
        if date_from:
            conditions.append("timestamp >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("timestamp <= ?")
            params.append(date_to)

        where = " AND ".join(conditions)
        try:
            rows = self._conn.execute(
                f"SELECT execution_id, event_id, correlation_id, task_id, workflow_id, "
                f"agent, model, provider, runtime, attempt, status, duration_ms, timestamp "
                f"FROM telemetry_executions "
                f"WHERE {where} "
                f"ORDER BY timestamp DESC "
                f"LIMIT ?",
                params + [limit],
            ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("query_executions failed: %s", exc)
            return []

        return [
            {
                "execution_id": row[0],
                "event_id": row[1],
                "correlation_id": row[2],
                "task_id": row[3],
                "workflow_id": row[4],
                "agent": row[5],
                "model": row[6],
                "provider": row[7],
                "runtime": row[8],
                "attempt": row[9],
                "status": row[10],
                "duration_ms": row[11],
                "timestamp": row[12],
            }
            for row in rows
        ]

    def aggregate_usage(
        self,
        *,
        agent: str | None = None,
        model: str | None = None,
        workflow_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict:
        usage_rows = self.query_usage(
            agent=agent,
            model=model,
            workflow_id=workflow_id,
            date_from=date_from,
            date_to=date_to,
            limit=10000,
        )
        cost_rows = self.query_costs(
            agent=agent,
            model=model,
            workflow_id=workflow_id,
            date_from=date_from,
            date_to=date_to,
            limit=10000,
        )

        total_input = sum(r["input_tokens"] or 0 for r in usage_rows)
        total_output = sum(r["output_tokens"] or 0 for r in usage_rows)
        total_tokens_val = sum(r["total_tokens"] or 0 for r in usage_rows)
        if not total_tokens_val:
            total_tokens_val = total_input + total_output
        total_cost = sum(r["total_cost"] or 0.0 for r in cost_rows)

        by_agent: dict[str, dict] = {}
        for r in usage_rows:
            a = r["agent"] or "unknown"
            if a not in by_agent:
                by_agent[a] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "count": 0}
            by_agent[a]["input_tokens"] += r["input_tokens"] or 0
            by_agent[a]["output_tokens"] += r["output_tokens"] or 0
            by_agent[a]["total_tokens"] += r["total_tokens"] or 0
            by_agent[a]["count"] += 1

        by_model: dict[str, dict] = {}
        for r in usage_rows:
            m = r["model"] or "unknown"
            if m not in by_model:
                by_model[m] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "count": 0}
            by_model[m]["input_tokens"] += r["input_tokens"] or 0
            by_model[m]["output_tokens"] += r["output_tokens"] or 0
            by_model[m]["total_tokens"] += r["total_tokens"] or 0
            by_model[m]["count"] += 1

        return {
            "totals": {
                "input_tokens": total_input,
                "output_tokens": total_output,
                "total_tokens": total_tokens_val,
                "total_cost": round(total_cost, 4),
                "currency": "USD",
            },
            "by_agent": by_agent,
            "by_model": by_model,
            "records": usage_rows,
            "cost_records": cost_rows,
        }


def _now() -> str:
    return datetime.now(UTC).isoformat()
