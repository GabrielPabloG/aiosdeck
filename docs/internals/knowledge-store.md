# Knowledge Store

**Status**: Accepted
**Date**: 2026-08-08

## Context

AiosDeck agents need structured access to project knowledge: coding conventions
learned from the codebase, architecture decisions from ADRs, patterns from
reviews, research findings, and project DNA. This knowledge must persist across
sessions, be queryable, and be re-indexed incrementally as sources change.

The Knowledge Store is the abstraction layer for this — structured, incremental,
and backend-agnostic. It lives alongside Memory and Telemetry in
`.aios/memory.db` (namespace `knowledge_*`) and requires zero external
dependencies.

## Architecture

```
Discovery → Engine.index() → Store.index_document() → Chunking → Persist
                ↑                                               ↓
CLI (index/search/sources) ← Kernel.get_engine("knowledge") ← SQLite/FTS5
```

### Contracts (`models.py`)

| Type | Purpose |
|------|---------|
| `KnowledgeSource` | Logical origin: a file, skill, ADR, or report. Source ID is deterministic (sha256 of type+path). |
| `KnowledgeDocument` | A versioned document within a source. Document ID is deterministic (sha256 of source_id+path). |
| `KnowledgeChunk` | A slice of content with metadata. Chunk ID is deterministic (sha256 of source_id:position). Fields: content, content_hash, position, token_estimate, optional embedding. |
| `KnowledgeQuery` | Search parameters: text, limit, optional source type filter. |
| `KnowledgeResult` | Search hit: content + source metadata. No score field (future). |

### Chunking Pipeline (`chunking.py`)

Pure functions, deterministic:

1. **Normalize** — CRLF→LF, strip trailing whitespace, collapse blank lines.
2. **Hash** — sha256 of normalized content (document hash and per-chunk content_hash).
3. **Chunk** per content type:
   - Markdown (adr, documentation, research, skill, project_dna): split on `^#{1,6}` headings; fallback: size-based with overlap.
   - Code: split on top-level `^(class |def |async def )`; fallback: size-based.
4. **Token estimate** — word count (simple, no tokenizer).

Chunk IDs are deterministic: `sha256(source_id + ":" + position)`. Same input always produces the same chunks with the same IDs and hashes.

### Incremental Policy (`store.py`)

```
index_document(doc):
  compute doc_hash = sha256(normalized(content))
  check existing document by document_id + project_id
  if exists AND doc_hash == stored_hash → skip (no-op)
  if exists AND doc_hash != stored_hash → reindex:
    delete old chunks + FTS rows
    re-chunk content
    insert new chunks + FTS rows
    update sources/documents hash + indexed_at
  if not exists → initial index
```

### Schema (`.aios/memory.db`, tables `knowledge_*`)

| Table | Purpose |
|-------|---------|
| `knowledge_sources` | Source registry: source_id (PK with project_id), type, path, hash, version, status. |
| `knowledge_documents` | Document versions: document_id (PK), source_id, title, path, hash, indexed_at. |
| `knowledge_chunks` | Chunk content: chunk_id (PK), source_id, document_id, content, content_hash, position, token_estimate. |
| `knowledge_index_runs` | Audit trail: run_id (PK), sources_scanned, sources_skipped, sources_reindexed, chunks_created, chunks_deleted, status. |
| `knowledge_fts` | FTS5 virtual table for full-text search. Fallback: LIKE on content. |

### Source Discovery (`discovery.py`)

Automatic detection when running `aios knowledge index`:

| Pattern | Source Type |
|---------|-------------|
| `.opencode/skills/project-dna/**` | `project_dna` |
| `.opencode/skills/*/SKILL.md` | `skill` |
| `docs/decisions/*.md` | `adr` |
| `docs/reports/*.md` | `research` |
| `docs/**/*.md` (excl. decisions, reports) | `documentation` |
| `src/**/*.py` (excl. `__pycache__`) | `code` |
| — | `memory` (reserved, not auto-detected) |

Candidates are sorted deterministically (type, then path).

### CLI

```bash
aios knowledge index              # Index all discovered sources
aios knowledge search "auth"      # FTS5 search with LIKE fallback
aios knowledge sources            # List indexed sources
aios k                            # Alias for knowledge
```

### Future

- Embedding field on chunks is reserved. A future re-embed hook (`_reindex_embeddings`) is prepared.
- Semantic search via vector DB is a post-v1.0 concern.
- `memory` source type is supported in contracts but not auto-discovered — reserved for indexing `.aios/memory.db` knowledge tables.
