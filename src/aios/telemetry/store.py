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

CREATE TABLE IF NOT EXISTS telemetry_retrieval (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent TEXT NOT NULL DEFAULT '',
    query TEXT NOT NULL DEFAULT '',
    chunks_retrieved INTEGER NOT NULL DEFAULT 0,
    chunks_selected INTEGER NOT NULL DEFAULT 0,
    tokens_before INTEGER NOT NULL DEFAULT 0,
    tokens_after INTEGER NOT NULL DEFAULT 0,
    compression_ratio REAL NOT NULL DEFAULT 0.0,
    retrieval_latency_ms REAL NOT NULL DEFAULT 0.0,
    retriever TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_tr_agent ON telemetry_retrieval(agent);
CREATE INDEX IF NOT EXISTS idx_tr_timestamp ON telemetry_retrieval(timestamp);

CREATE TABLE IF NOT EXISTS telemetry_skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT DEFAULT '',
    correlation_id TEXT DEFAULT '',
    skill_name TEXT NOT NULL,
    skill_version TEXT DEFAULT '1',
    intent TEXT DEFAULT '',
    agent TEXT DEFAULT '',
    considered INTEGER DEFAULT 0,
    selected INTEGER DEFAULT 0,
    used INTEGER DEFAULT 0,
    relevance_score REAL DEFAULT 0.0,
    tokens_contributed INTEGER DEFAULT 0,
    downstream_success INTEGER,
    timestamp TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_ts_skill_name ON telemetry_skills(skill_name);
CREATE INDEX IF NOT EXISTS idx_ts_agent ON telemetry_skills(agent);
CREATE INDEX IF NOT EXISTS idx_ts_timestamp ON telemetry_skills(timestamp);

CREATE TABLE IF NOT EXISTS telemetry_gates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gate TEXT NOT NULL,
    status TEXT NOT NULL,
    correlation_id TEXT NOT NULL DEFAULT '',
    duration_ms REAL,
    findings_low INTEGER NOT NULL DEFAULT 0,
    findings_medium INTEGER NOT NULL DEFAULT 0,
    findings_high INTEGER NOT NULL DEFAULT 0,
    findings_critical INTEGER NOT NULL DEFAULT 0,
    blocked INTEGER NOT NULL DEFAULT 0,
    overridden INTEGER NOT NULL DEFAULT 0,
    timestamp TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_tg_gate ON telemetry_gates(gate);
CREATE INDEX IF NOT EXISTS idx_tg_status ON telemetry_gates(status);
CREATE INDEX IF NOT EXISTS idx_tg_timestamp ON telemetry_gates(timestamp);
CREATE INDEX IF NOT EXISTS idx_tg_correlation ON telemetry_gates(correlation_id);

CREATE TABLE IF NOT EXISTS telemetry_security (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision TEXT NOT NULL,
    agent TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL DEFAULT '',
    allowed INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    violations TEXT NOT NULL DEFAULT '[]',
    intent_source TEXT NOT NULL DEFAULT '',
    correlation_id TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_tsec_decision ON telemetry_security(decision);
CREATE INDEX IF NOT EXISTS idx_tsec_agent ON telemetry_security(agent);
CREATE INDEX IF NOT EXISTS idx_tsec_allowed ON telemetry_security(allowed);
CREATE INDEX IF NOT EXISTS idx_tsec_timestamp ON telemetry_security(timestamp);
CREATE INDEX IF NOT EXISTS idx_tsec_correlation ON telemetry_security(correlation_id);
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

    # ------------------------------------------------------------------
    # Retrieval metrics
    # ------------------------------------------------------------------

    def insert_retrieval(self, record: dict) -> None:
        if not self._conn:
            return
        try:
            self._conn.execute(
                """INSERT INTO telemetry_retrieval
                   (agent, query, chunks_retrieved, chunks_selected,
                    tokens_before, tokens_after, compression_ratio,
                    retrieval_latency_ms, retriever, timestamp, project_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.get("agent", ""),
                    record.get("query", ""),
                    record.get("chunks_retrieved", 0),
                    record.get("chunks_selected", 0),
                    record.get("tokens_before", 0),
                    record.get("tokens_after", 0),
                    record.get("compression_ratio", 0.0),
                    record.get("retrieval_latency_ms", 0.0),
                    record.get("retriever", ""),
                    record.get("timestamp", _now()),
                    self._project_id,
                ),
            )
            self._conn.commit()
        except sqlite3.Error as exc:
            logger.warning("insert_retrieval failed: %s", exc)

    def query_retrieval(
        self,
        *,
        agent: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        if not self._conn:
            return []

        conditions = ["project_id = ?"]
        params: list = [self._project_id]

        if agent:
            conditions.append("agent = ?")
            params.append(agent)

        where = " AND ".join(conditions)
        try:
            rows = self._conn.execute(
                f"SELECT id, agent, query, chunks_retrieved, chunks_selected, "
                f"tokens_before, tokens_after, compression_ratio, "
                f"retrieval_latency_ms, retriever, timestamp "
                f"FROM telemetry_retrieval "
                f"WHERE {where} "
                f"ORDER BY timestamp DESC "
                f"LIMIT ?",
                params + [limit],
            ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("query_retrieval failed: %s", exc)
            return []

        return [
            {
                "id": row[0],
                "agent": row[1],
                "query": row[2],
                "chunks_retrieved": row[3],
                "chunks_selected": row[4],
                "tokens_before": row[5],
                "tokens_after": row[6],
                "compression_ratio": row[7],
                "retrieval_latency_ms": row[8],
                "retriever": row[9],
                "timestamp": row[10],
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Skill usage records
    # ------------------------------------------------------------------

    def insert_skill_usage(self, record: dict) -> None:
        if not self._conn:
            return
        try:
            self._conn.execute(
                """INSERT INTO telemetry_skills
                   (execution_id, correlation_id, skill_name, skill_version,
                    intent, agent, considered, selected, used,
                    relevance_score, tokens_contributed, downstream_success,
                    timestamp, project_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.get("execution_id", ""),
                    record.get("correlation_id", ""),
                    record.get("skill_name", ""),
                    record.get("skill_version", "1"),
                    record.get("intent", ""),
                    record.get("agent", ""),
                    record.get("considered", 0),
                    record.get("selected", 0),
                    record.get("used", 0),
                    record.get("relevance_score", 0.0),
                    record.get("tokens_contributed", 0),
                    record.get("downstream_success"),
                    record.get("timestamp", _now()),
                    self._project_id,
                ),
            )
            self._conn.commit()
        except sqlite3.Error as exc:
            logger.warning("insert_skill_usage failed: %s", exc)

    def query_skill_stats(
        self,
        *,
        skill: str | None = None,
        agent: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        if not self._conn:
            return []

        conditions = ["project_id = ?"]
        params: list = [self._project_id]

        if skill:
            conditions.append("skill_name = ?")
            params.append(skill)
        if agent:
            conditions.append("agent = ?")
            params.append(agent)
        if date_from:
            conditions.append("timestamp >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("timestamp <= ?")
            params.append(date_to)

        where = " AND ".join(conditions)
        try:
            query = f"""SELECT
                    skill_name,
                    COUNT(*) as total_records,
                    SUM(considered) as total_considered,
                    SUM(selected) as total_selected,
                    SUM(used) as total_used,
                    AVG(CASE WHEN relevance_score > 0 THEN relevance_score END) as avg_relevance,
                    SUM(tokens_contributed) as total_tokens
                FROM telemetry_skills
                WHERE {where}
                GROUP BY skill_name
                ORDER BY total_used DESC, total_selected DESC
                LIMIT ?"""
            rows = self._conn.execute(query, params + [limit]).fetchall()
        except sqlite3.Error as exc:
            logger.warning("query_skill_stats failed: %s", exc)
            return []

        return [
            {
                "skill_name": row[0],
                "total_records": row[1],
                "total_considered": row[2],
                "total_selected": row[3],
                "total_used": row[4],
                "avg_relevance": row[5],
                "total_tokens": row[6],
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Gate telemetry records
    # ------------------------------------------------------------------

    def insert_gate_record(self, record: dict) -> None:
        if not self._conn:
            return
        try:
            self._conn.execute(
                """INSERT INTO telemetry_gates
                   (gate, status, correlation_id, duration_ms,
                    findings_low, findings_medium, findings_high, findings_critical,
                    blocked, overridden, timestamp, project_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.get("gate", ""),
                    record.get("status", ""),
                    record.get("correlation_id", ""),
                    record.get("duration_ms"),
                    record.get("findings_low", 0),
                    record.get("findings_medium", 0),
                    record.get("findings_high", 0),
                    record.get("findings_critical", 0),
                    1 if record.get("blocked") else 0,
                    1 if record.get("overridden") else 0,
                    record.get("timestamp", _now()),
                    self._project_id,
                ),
            )
            self._conn.commit()
        except sqlite3.Error as exc:
            logger.warning("insert_gate_record failed: %s", exc)

    def query_gate_stats(  # noqa: PLR0913
        self,
        *,
        gate: str | None = None,
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        if not self._conn:
            return []

        conditions = ["project_id = ?"]
        params: list = [self._project_id]

        if gate:
            conditions.append("gate = ?")
            params.append(gate)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if date_from:
            conditions.append("timestamp >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("timestamp <= ?")
            params.append(date_to)

        where = " AND ".join(conditions)
        try:
            rows = self._conn.execute(
                f"""SELECT gate,
                    COUNT(*) as runs,
                    COALESCE(SUM(CASE WHEN status = 'passed' THEN 1 ELSE 0 END), 0) as passed,
                    COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) as failed,
                    COALESCE(SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END), 0) as skipped,
                    COALESCE(SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END), 0) as errored,
                    COALESCE(SUM(blocked), 0) as blocked,
                    COALESCE(SUM(overridden), 0) as overridden,
                    AVG(duration_ms) as avg_duration_ms,
                    COALESCE(SUM(findings_low), 0) as findings_low,
                    COALESCE(SUM(findings_medium), 0) as findings_medium,
                    COALESCE(SUM(findings_high), 0) as findings_high,
                    COALESCE(SUM(findings_critical), 0) as findings_critical
                FROM telemetry_gates
                WHERE {where}
                GROUP BY gate
                ORDER BY runs DESC
                LIMIT ?""",
                params + [limit],
            ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("query_gate_stats failed: %s", exc)
            return []

        return [
            {
                "gate": row[0],
                "runs": row[1],
                "passed": row[2],
                "failed": row[3],
                "skipped": row[4],
                "errored": row[5],
                "blocked": row[6],
                "overridden": row[7],
                "avg_duration_ms": row[8],
                "findings_low": row[9],
                "findings_medium": row[10],
                "findings_high": row[11],
                "findings_critical": row[12],
            }
            for row in rows
        ]

    def query_gate_records(  # noqa: PLR0913
        self,
        *,
        gate: str | None = None,
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        if not self._conn:
            return []

        conditions = ["project_id = ?"]
        params: list = [self._project_id]

        if gate:
            conditions.append("gate = ?")
            params.append(gate)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if date_from:
            conditions.append("timestamp >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("timestamp <= ?")
            params.append(date_to)

        where = " AND ".join(conditions)
        try:
            rows = self._conn.execute(
                f"""SELECT id, gate, status, correlation_id, duration_ms,
                    findings_low, findings_medium, findings_high, findings_critical,
                    blocked, overridden, timestamp
                FROM telemetry_gates
                WHERE {where}
                ORDER BY timestamp DESC
                LIMIT ?""",
                params + [limit],
            ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("query_gate_records failed: %s", exc)
            return []

        return [
            {
                "id": row[0],
                "gate": row[1],
                "status": row[2],
                "correlation_id": row[3],
                "duration_ms": row[4],
                "findings_low": row[5],
                "findings_medium": row[6],
                "findings_high": row[7],
                "findings_critical": row[8],
                "blocked": row[9],
                "overridden": row[10],
                "timestamp": row[11],
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Security audit records
    # ------------------------------------------------------------------

    def insert_security_decision(self, record: dict) -> None:
        if not self._conn:
            return
        violations = record.get("violations") or []
        if not isinstance(violations, str):
            violations = json.dumps(list(violations), ensure_ascii=False)
        try:
            self._conn.execute(
                """INSERT INTO telemetry_security
                   (decision, agent, action, allowed, reason,
                    violations, intent_source, correlation_id,
                    timestamp, project_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.get("decision", ""),
                    record.get("agent", ""),
                    record.get("action", ""),
                    1 if record.get("allowed") else 0,
                    record.get("reason", ""),
                    violations,
                    record.get("intent_source", ""),
                    record.get("correlation_id", ""),
                    record.get("timestamp", _now()),
                    self._project_id,
                ),
            )
            self._conn.commit()
        except sqlite3.Error as exc:
            logger.warning("insert_security_decision failed: %s", exc)

    def query_security_stats(  # noqa: PLR0913
        self,
        *,
        decision: str | None = None,
        agent: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        if not self._conn:
            return []

        conditions = ["project_id = ?"]
        params: list = [self._project_id]

        if decision:
            conditions.append("decision = ?")
            params.append(decision)
        if agent:
            conditions.append("agent = ?")
            params.append(agent)
        if date_from:
            conditions.append("timestamp >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("timestamp <= ?")
            params.append(date_to)

        where = " AND ".join(conditions)
        try:
            rows = self._conn.execute(
                f"""SELECT decision,
                    COUNT(*) as runs,
                    COALESCE(SUM(CASE WHEN allowed = 1 THEN 1 ELSE 0 END), 0) as allowed,
                    COALESCE(SUM(CASE WHEN allowed = 0 THEN 1 ELSE 0 END), 0) as denied
                FROM telemetry_security
                WHERE {where}
                GROUP BY decision
                ORDER BY runs DESC
                LIMIT ?""",
                params + [limit],
            ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("query_security_stats failed: %s", exc)
            return []

        return [
            {
                "decision": row[0],
                "runs": row[1],
                "allowed": row[2],
                "denied": row[3],
            }
            for row in rows
        ]

    def query_security_records(  # noqa: PLR0913
        self,
        *,
        decision: str | None = None,
        agent: str | None = None,
        allowed: bool | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        if not self._conn:
            return []

        conditions = ["project_id = ?"]
        params: list = [self._project_id]

        if decision:
            conditions.append("decision = ?")
            params.append(decision)
        if agent:
            conditions.append("agent = ?")
            params.append(agent)
        if allowed is not None:
            conditions.append("allowed = ?")
            params.append(1 if allowed else 0)
        if date_from:
            conditions.append("timestamp >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("timestamp <= ?")
            params.append(date_to)

        where = " AND ".join(conditions)
        try:
            rows = self._conn.execute(
                f"""SELECT id, decision, agent, action, allowed, reason,
                    violations, intent_source, correlation_id, timestamp
                FROM telemetry_security
                WHERE {where}
                ORDER BY timestamp DESC
                LIMIT ?""",
                params + [limit],
            ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("query_security_records failed: %s", exc)
            return []

        return [
            {
                "id": row[0],
                "decision": row[1],
                "agent": row[2],
                "action": row[3],
                "allowed": row[4],
                "reason": row[5],
                "violations": json.loads(row[6]) if row[6] else [],
                "intent_source": row[7],
                "correlation_id": row[8],
                "timestamp": row[9],
            }
            for row in rows
        ]


def _now() -> str:
    return datetime.now(UTC).isoformat()
