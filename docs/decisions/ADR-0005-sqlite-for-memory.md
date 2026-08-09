# ADR-0005 — SQLite for Memory Persistence

**Status**: Implemented
**Level**: Implementation
**Review date**: 2026-08-09
**Date**: 2026-08-02

## Context

The Memory Engine must persist knowledge across sessions: conventions learned from the codebase, decisions documented in ADRs, patterns identified by reviewers, mistakes to avoid. This data must survive restarts, be queryable, and never leave the developer's machine.

We evaluated four storage options:

| Option | Description |
|--------|-------------|
| **JSON/YAML files** | Store memories as flat files in the project directory |
| **SQLite** | Single-file relational database with SQL queries and FTS |
| **PostgreSQL** | External database server with advanced query capabilities |
| **Vector database** | Embedding-based semantic search (Chroma, Qdrant, pgvector) |

## Decision

**Use SQLite for memory persistence.** SQLite is a single file. It requires no server, no configuration, no network access. It is available in Python's standard library (`sqlite3`). It supports full-text search (FTS5) for convention and decision lookup. It supports structured queries for filtering by category, status, and project.

The database file resolves in this order:
1. `./.aios/memory.db` — project-scoped, the default.
2. `~/.local/share/aiosdeck/memory.db` — global fallback when the project is
   outside a writable `.aios` directory.

One file, one project's accumulated knowledge.

## Consequences

### Positive

- **Zero dependencies**: SQLite is part of Python's standard library. No pip install, no Docker container, no cloud service.
- **Local-first**: Memory never leaves the developer's machine. Privacy is guaranteed by architecture, not by policy.
- **Single file**: Backup, migration, and inspection are trivial. `sqlite3 memory.db .dump` exports the entire knowledge base.
- **Proven reliability**: SQLite is the most deployed database engine in the world. It is tested more thoroughly than any alternative.
- **FTS5**: Full-text search enables fuzzy recall — "find conventions about naming" works without exact matches.

### Negative

- **Single-writer**: SQLite serializes writes. Multiple concurrent agents writing to memory simultaneously will contend. This is acceptable for v0.3–v0.8 where agents run sequentially.
- **No vector search**: Semantic search ("find patterns similar to this one") requires embeddings. SQLite with FTS5 provides keyword search, not semantic search.
- **Schema migrations**: Adding new memory types requires schema changes. Migration scripts must be maintained.

### Neutral

- Vector search for semantic memory recall is a post-v1.0 concern. SQLite handles structured recall for the foreseeable future.
- If concurrent writes become a bottleneck (v0.8+ multi-agent), WAL mode and connection pooling mitigate the issue without switching databases.
- The Memory Engine's store abstraction isolates the storage backend. If SQLite is replaced, only `memory/store.py` changes.
