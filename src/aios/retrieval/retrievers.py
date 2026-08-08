"""Retriever protocols and implementations — Keyword, Vector."""

from __future__ import annotations

import json
import logging
import math
import re
from typing import Protocol

from aios.knowledge.models import KnowledgeQuery, KnowledgeResult
from aios.knowledge.store import SQLiteKnowledgeStore

logger = logging.getLogger("aios.retrieval.retrievers")

_QUERY_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]{2,}")
_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "does",
        "for",
        "from",
        "how",
        "in",
        "into",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "what",
        "when",
        "where",
        "which",
        "with",
        "do",
        "should",
        "we",
        "you",
        "i",
        "me",
        "my",
    }
)


class ScoredResult:
    __slots__ = ("result", "score", "justification")

    def __init__(self, result: KnowledgeResult, score: float, justification: str = "") -> None:
        self.result = result
        self.score = score
        self.justification = justification

    def __repr__(self) -> str:
        return f"ScoredResult(score={self.score:.3f}, content={self.result.content[:60]!r})"


class Retriever(Protocol):
    def retrieve(
        self, query: str, *, k: int, filters: dict | None = None
    ) -> list[ScoredResult]: ...


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _QUERY_TOKEN_RE.findall(text) if t.lower() not in _STOPWORDS]


def _lexical_score(query_tokens: list[str], content: str) -> float:
    if not query_tokens:
        return 0.0
    lowered = content.lower()
    matches = sum(1 for t in query_tokens if t in lowered)
    return matches / len(query_tokens)


class KeywordRetriever:
    def __init__(self, store: SQLiteKnowledgeStore) -> None:
        self._store = store

    def retrieve(self, query: str, *, k: int, filters: dict | None = None) -> list[ScoredResult]:
        text = query.strip()
        if not text:
            return []

        source_types: list[str] | None = None
        if filters and "source_types" in filters:
            source_types = filters["source_types"]

        results = self._store.search(
            KnowledgeQuery(text=text, limit=max(k, 20), source_types=source_types)
        )

        tokens = _tokenize(text)
        scored: list[ScoredResult] = []
        for r in results:
            score = _lexical_score(tokens, r.content)
            if score <= 0.0:
                continue
            scored.append(ScoredResult(result=r, score=score))

        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:k]


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    raw = dot / (norm_a * norm_b)
    return max(-1.0, min(1.0, raw))


def _parse_vector_blob(blob: str, expected_dim: int) -> list[float] | None:
    try:
        vec = json.loads(blob)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(vec, list) or len(vec) != expected_dim:
        return None
    if not all(isinstance(v, (int, float)) for v in vec):
        return None
    return [float(v) for v in vec]


class VectorRetriever:
    def __init__(self, store: SQLiteKnowledgeStore, provider) -> None:
        self._store = store
        self._provider = provider

    def retrieve(  # noqa: PLR0911, PLR0912
        self, query: str, *, k: int, filters: dict | None = None
    ) -> list[ScoredResult]:
        text = query.strip()
        if not text:
            return []

        source_types: list[str] | None = None
        if filters and "source_types" in filters:
            source_types = filters["source_types"]

        candidates = self._store.search(
            KnowledgeQuery(text=text, limit=max(k, 20), source_types=source_types)
        )
        if not candidates:
            return []

        chunk_ids = [c.chunk_id for c in candidates]
        stored = self._store.get_embeddings_by_chunk_ids(chunk_ids)
        if not stored:
            return []

        emb_map: dict[str, list[float]] = {}
        dim = None
        for emb in stored:
            if dim is None:
                dim = emb["vector_dim"]
            if emb["vector_dim"] != dim:
                continue
            vec = _parse_vector_blob(emb["vector_blob"], dim)
            if vec is not None:
                emb_map[emb["chunk_id"]] = vec

        if not emb_map:
            return []

        try:
            query_vecs = self._provider.embed([query])
        except Exception as exc:
            logger.warning("VectorRetriever: query embedding failed, returning empty: %s", exc)
            return []

        if not query_vecs:
            return []
        query_vec = query_vecs[0]

        scored: list[ScoredResult] = []
        for c in candidates:
            if c.chunk_id not in emb_map:
                continue
            sim = _cosine(query_vec, emb_map[c.chunk_id])
            if sim > 0.0:
                scored.append(ScoredResult(result=c, score=sim))

        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:k]
