"""Embedding provider contracts — protocol + Ollama implementation."""

from __future__ import annotations

import hashlib
import json
import logging
import urllib.request
from typing import Protocol

logger = logging.getLogger("aios.retrieval.providers")

_HTTP_OK = 200


class EmbeddingError(Exception):
    """Domain error for embedding provider failures."""


class EmbeddingProvider(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def dimensions(self) -> int: ...

    def available(self) -> bool: ...


class OllamaEmbeddingProvider:
    name = "ollama"

    def __init__(
        self,
        model: str = "",
        host: str = "",
        dimensions: int = 0,
    ) -> None:
        self._model = model or "nomic-embed-text"
        self._host = (host or "http://localhost:11434").rstrip("/")
        self._dims = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        url = f"{self._host}/api/embed"
        payload = json.dumps({"model": self._model, "input": texts}).encode()
        headers = {"Content-Type": "application/json"}
        req = urllib.request.Request(url, data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode()
        except (OSError, TimeoutError) as exc:
            raise EmbeddingError(f"Ollama embed request failed: {exc}") from exc
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise EmbeddingError(f"Invalid JSON from Ollama: {exc}") from exc
        vectors: list[list[float]] = data.get("embeddings", [])
        if not vectors:
            logger.warning("Ollama returned empty embeddings for %d texts", len(texts))
            return []
        if self._dims == 0 and vectors:
            self._dims = len(vectors[0])
        return vectors

    def dimensions(self) -> int:
        return self._dims

    def available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self._host}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == _HTTP_OK
        except (OSError, TimeoutError):
            return False


class FakeEmbeddingProvider:
    name = "fake"

    def __init__(self, dims: int = 4) -> None:
        self._dims = dims

    def embed(self, texts: list[str]) -> list[list[float]]:
        result: list[list[float]] = []
        for t in texts:
            seed = int(hashlib.sha256(t.encode()).hexdigest()[:8], 16)
            result.append([(seed + i) / 1e9 for i in range(self._dims)])
        return result

    def dimensions(self) -> int:
        return self._dims

    def available(self) -> bool:
        return True
