# Retrieval Flow & Token Budget (v0.9.5)

**Status**: Accepted
**Date**: 2026-08-08

## Context

AiosDeck needs to maximize relevant context per token, not just retrieve
everything that matches a query. The Retrieval Engine provides a pipeline
that retrieves, ranks, filters, and selects the most relevant chunks within
a per-agent token budget.

## Architecture

```
CLI (aios knowledge retrieve)
      │
      ▼
KnowledgeEngine.retrieve() → ContextSelector → KeywordRetriever / VectorRetriever
                                    │
                                    ▼
                            [retrieve 20] → [rank + boost] → [dedupe]
                                    │
                                    ▼
                            [select ≤ budget] → [prompt_context]
                                    │
                                    ▼
                            TelemetryEngine.record_retrieval()
```

## Components

### EmbeddingProvider (`aios.retrieval.providers`)

Protocol:
- `embed(texts: list[str]) -> list[list[float]]` — generate vectors
- `dimensions() -> int` — vector dimensionality
- `available() -> bool` — health check
- `name` — provider identifier

Implementations:
- `OllamaEmbeddingProvider` — uses `POST /api/embed` against a local Ollama
  server. Host from `AIOS_OLLAMA_HOST` (default `http://localhost:11434`),
  model from `AIOS_EMBEDDING_MODEL` (default `nomic-embed-text`).
  Zero external dependencies (stdlib `urllib`).
- `FakeEmbeddingProvider` — test-only deterministic provider (hash-based).

### Retrievers (`aios.retrieval.retrievers`)

Protocol: `retrieve(query, k, filters) -> list[ScoredResult]`

| Retriever | Strategy | When Active |
|-----------|----------|-------------|
| `KeywordRetriever` | Lexical overlap over FTS5 results | Always |
| `VectorRetriever` | Cosine similarity over stored embeddings | Only via `--vector` flag + Ollama available + embeddings present |

**Fallback**: VectorRetriever returns `[]` when embeddings are missing; the
ContextSelector falls back to the KeywordRetriever automatically.

### ContextSelector (`aios.retrieval.selector`)

Pipeline (mandatory):
1. `retrieve(20)` — from the active retriever
2. `rank` — score + source type boost (code: +0.10, adr: +0.08, skill: +0.07, etc.)
3. `dedupe` — keep highest-scored chunk per source
4. `select(≤ budget)` — greedy by score until the token budget is exhausted
5. Truncation — oversized chunks are truncated to fit the budget (word-based)
6. `prompt_context` — formatted `[Knowledge]` block

Output (`SelectionResult`):
- `chunks` — selected `ScoredResult` list with scores and justifications
- `prompt_context` — formatted string for injection
- `metrics` — `tokens_before`, `tokens_after`, `compression_ratio`, `retrieval_latency_ms`

### ContextBudget

Per-agent token budgets (configurable via constructor overrides):

| Agent | Budget (tokens) |
|-------|-----------------|
| `planner` | 3000 |
| `research` | 5000 |
| `reviewer` | 2000 |
| unknown | 3000 (fallback) |

## Embeddings (`knowledge_embeddings`)

Table in `.aios/memory.db`:

| Column | Purpose |
|--------|---------|
| `chunk_id` | FK to `knowledge_chunks` |
| `provider` | Embedding provider name |
| `model` | Model name (e.g., `nomic-embed-text`) |
| `vector_dim` | Dimensionality |
| `vector_blob` | JSON array of floats |
| `embedding_hash` | `sha256(content_hash | provider | model)` — incremental re-embed key |
| `created_at` | Timestamp |
| `project_id` | Project isolation |

**Incremental re-embed**: `KnowledgeEngine.embed_indexed()` finds chunks
without embeddings (or with stale `embedding_hash`) and batches them through
the provider. Skipped chunks are not re-embedded. Re-indexing a source
deletes its old embeddings automatically.

### Usage

```bash
# Index with embeddings
aios knowledge index --embed

# Retrieve (keyword-only, default)
aios knowledge retrieve "how does authentication work"

# Retrieve with vector similarity
aios knowledge retrieve "authentication flow" --vector

# Per-agent budget
aios knowledge retrieve "auth" --agent planner

# JSON output
aios knowledge retrieve "auth" --json
```

## Telemetry

Per-retrieval metrics persisted in `telemetry_retrieval`:

| Field | Purpose |
|-------|---------|
| `retrieval_latency_ms` | Time from query to selection |
| `chunks_retrieved` | Total candidates (always ≤ 20) |
| `chunks_selected` | Chosen after rank/filter/select |
| `tokens_before` | Σ token estimates of all retrieved |
| `tokens_after` | Σ token estimates of selected |
| `compression_ratio` | `1 - (tokens_after / tokens_before)` |

Formula: `compression_ratio = 1 - (tokens_after / tokens_before)`

## Design Decisions

- **Core decoupled from Ollama** — `KnowledgeEngine` accepts an
  `EmbeddingProvider` protocol; the CLI composition root constructs it.
- **Vector off by default** — `retrieve()` only uses vector when
  `use_vector=True` is explicitly passed. Default is keyword-only.
- **Fallback, never fail** — Missing embeddings, unavailable provider, or
  empty index all return gracefully with an empty or keyword-only result.
- **No external dependencies** — core (`aios/retrieval/`) depends only on
  stdlib and the existing `aios/knowledge/` package.
