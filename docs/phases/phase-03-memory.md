# Phase 03 — Memory Engine

**Status**: Implemented
**Level**: Implementation
**Review date**: 2026-08-09
**Date**: 2026-08-02
**Target Version**: v0.3

## Context

Agents without memory are amnesiacs. Every conversation starts from zero. Every session re-discovers conventions that were learned yesterday. The Memory Engine solves this: it persists knowledge across sessions so the system gets smarter over time.

Memory is not a cache. It is not a configuration file. It is a first-class system component with its own engine, schema, and lifecycle. The principle is: **memory is part of the system**.

## Decision

### Architecture

```
Memory Engine
   │
   ├── Store (SQLite)
   │     ├── conventions table
   │     ├── decisions table
   │     ├── patterns table
   │     ├── mistakes table
   │     └── sessions table
   │
   ├── Indexer
   │     └── Full-text search on conventions and decisions
   │
   ├── Recall Engine
   │     └── Retrieves relevant memories based on context
   │
   └── Ingest Engine
         └── Stores new knowledge from agent outputs
```

### Schema

```sql
CREATE TABLE conventions (
    id INTEGER PRIMARY KEY,
    category TEXT NOT NULL,         -- naming, style, structure, imports
    rule TEXT NOT NULL,             -- "Use snake_case for variables"
    source TEXT,                    -- "README.md", "conversation", "manual"
    project_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE decisions (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,            -- "Use SQLite for persistence"
    context TEXT,                   -- Why this decision was made
    decision TEXT NOT NULL,         -- What was decided
    consequences TEXT,              -- Known trade-offs
    status TEXT DEFAULT 'active',   -- active, superseded, deprecated
    project_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE patterns (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,             -- "Repository Pattern", "Factory Pattern"
    description TEXT,
    usage_count INTEGER DEFAULT 0,
    project_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE mistakes (
    id INTEGER PRIMARY KEY,
    description TEXT NOT NULL,      -- "Never import * in module __init__.py"
    category TEXT,                  -- security, performance, style, correctness
    severity TEXT DEFAULT 'warning',-- info, warning, critical
    project_id TEXT NOT NULL,
    resolved_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE sessions (
    id INTEGER PRIMARY KEY,
    started_at TIMESTAMP,
    ended_at TIMESTAMP,
    workflow_count INTEGER DEFAULT 0,
    task_count INTEGER DEFAULT 0,
    agent_used TEXT,                -- JSON array of agent names
    summary TEXT,
    project_id TEXT NOT NULL
);
```

### Event Contract

| Event | Direction | Description |
|-------|-----------|-------------|
| `session.start` | Consumed | Opens database connection for the session |
| `context.detected` | Consumed | Stores project metadata as conventions |
| `agent.completed` | Consumed | Extracts conventions, decisions, patterns from agent output |
| `quality.gate_passed` | Consumed | Records successful checks as reinforced conventions |
| `quality.gate_failed` | Consumed | Records failures as mistakes to avoid |
| `task.completed` | Consumed | Updates session task count |
| `session.shutdown` | Consumed | Writes session summary, closes connection |
| `memory.loaded` | Emitted | Published after restore is complete |
| `memory.updated` | Emitted | Published when new knowledge is stored |

### Recall Flow

When the Context Engine finishes detection, the Memory Engine enriches the context:

```python
async def on_context_detected(self, event: Event) -> None:
    project_id = event.payload.project_id
    context = event.payload

    # Recall relevant knowledge for this project
    conventions = await self.store.get_conventions(project_id)
    decisions = await self.store.get_decisions(project_id, status="active")
    mistakes = await self.store.get_mistakes(project_id, resolved_at=None)
    patterns = await self.store.get_patterns(project_id)

    # Enrich context with memory
    context["memory"] = {
        "conventions": conventions,
        "decisions": decisions,
        "mistakes": [m.description for m in mistakes],
        "patterns": [p.name for p in patterns],
    }

    await self.bus.publish("memory.loaded", context)
```

### Ingest Flow

When an agent completes a task, the Memory Engine extracts learnable patterns:

```python
async def on_agent_completed(self, event: Event) -> None:
    output = event.payload.output
    project_id = event.payload.project_id

    # Extract conventions from code patterns
    if self._contains_new_convention(output):
        rule = self._extract_convention(output)
        await self.store.upsert_convention(project_id, rule)

    # Extract decisions from explicit statements
    if self._contains_decision(output):
        decision = self._extract_decision(output)
        await self.store.add_decision(project_id, decision)
```

Extraction uses simple heuristics in v0.3. Future versions will use the Memory Engine itself (agent-based extraction) for richer recall.

### Search

Full-text search enabled on conventions and decisions:

```sql
CREATE VIRTUAL TABLE conventions_fts USING fts5(category, rule, content=conventions);
```

Queries are trigram-based for fuzzy matching.

### Storage Location

```
~/.local/share/aiosdeck/memory.db
```

Override via `AIOS_MEMORY_PATH` or `~/.config/aiosdeck/config.yaml`.

## Consequences

### Positive

- **Persistent learning**: The system improves across sessions without manual effort.
- **Structured knowledge**: Schema ensures memories are queryable and indexable.
- **Minimal dependency**: SQLite is standard library. No database server required.
- **Privacy**: All memory is local. Nothing is sent to a cloud database.

### Negative

- **Extraction is heuristic**: Simple pattern matching misses nuance. Agent-extracted memory (future) will be more accurate.
- **Storage growth**: Memory accumulates indefinitely. No pruning mechanism in v0.3.
- **Domain-specific**: Memory is per-project. Cross-project patterns are not learned (yet).

### Neutral

- Memory is read-only for agents. Only the Memory Engine writes. This prevents contamination.
- Memory is not shared between users. Team memory is a post-v1.0 feature.

## Implementation Notes

- [ ] Implement `memory/store.py` — SQLite schema creation, CRUD operations
- [ ] Implement `memory/engine.py` — Event handlers, recall, ingest, search
- [ ] FTS5 full-text search must be enabled at compile time (standard in Python's sqlite3)
- [ ] Convention extraction: scan agent output for "use X", "follow Y", "prefer Z" patterns
- [ ] Decision extraction: scan for "decided to", "chose", "opted for" patterns
- [ ] Session summary: write on shutdown, include task count and agent usage
- [ ] Database path: `~/.local/share/aiosdeck/memory.db` with directory auto-creation
- [ ] Test: recall returns empty list for new project
- [ ] Test: ingest stores convention and it appears in next recall
- [ ] Test: session start → stop → start restores prior session data
- [ ] Test: convention deduplication (same rule with different source → update, not duplicate)
