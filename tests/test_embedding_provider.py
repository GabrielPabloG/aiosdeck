"""Tests for EmbeddingProvider protocol and OllamaEmbeddingProvider."""

import hashlib
from unittest.mock import MagicMock, patch

from aios.retrieval.providers import (
    EmbeddingError,
    OllamaEmbeddingProvider,
)


class FakeEmbeddingProvider:
    name = "fake"
    _vectors: list[list[float]]

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


class TestEmbeddingProviderProtocol:
    def test_fake_provider_conforms(self):
        provider = FakeEmbeddingProvider(dims=8)
        assert provider.name == "fake"

        texts = ["hello world", "goodbye"]
        vectors = provider.embed(texts)
        assert len(vectors) == 2
        assert len(vectors[0]) == 8
        assert len(vectors[1]) == 8

        assert provider.dimensions() == 8
        assert provider.available() is True

    def test_embed_empty_list(self):
        provider = FakeEmbeddingProvider()
        assert provider.embed([]) == []

    def test_deterministic_output(self):
        provider = FakeEmbeddingProvider(dims=4)
        v1 = provider.embed(["test"])[0]
        v2 = provider.embed(["test"])[0]
        assert v1 == v2


class TestOllamaEmbeddingProvider:
    def test_name_and_dimensions_default(self):
        provider = OllamaEmbeddingProvider()
        assert provider.name == "ollama"
        assert isinstance(provider.dimensions(), int)

    def test_name_and_dimensions_custom(self):
        provider = OllamaEmbeddingProvider(model="bge-m3", dimensions=1024)
        assert provider.name == "ollama"
        assert provider.dimensions() == 1024
        assert provider._model == "bge-m3"

    def test_available_true(self):
        with patch("urllib.request.urlopen") as mock:
            mock.return_value.__enter__.return_value.status = 200
            provider = OllamaEmbeddingProvider()
            assert provider.available() is True

    def test_available_false(self):
        with patch("urllib.request.urlopen") as mock:
            mock.side_effect = OSError("connection refused")
            provider = OllamaEmbeddingProvider()
            assert provider.available() is False

    def test_embed_success(self):
        provider = OllamaEmbeddingProvider(dimensions=4, host="http://localhost:11434")
        response_payload = '{"embeddings": [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]]}'

        with patch("urllib.request.urlopen") as mock_urlopen, patch("urllib.request.Request"):
            mock_resp = MagicMock()
            mock_resp.read.return_value = response_payload.encode()
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            vectors = provider.embed(["hello", "world"])
            assert len(vectors) == 2
            assert vectors[0] == [0.1, 0.2, 0.3, 0.4]
            assert vectors[1] == [0.5, 0.6, 0.7, 0.8]

    def test_embed_sets_dimensions_after_call(self):
        provider = OllamaEmbeddingProvider(host="http://localhost:11434")
        assert provider.dimensions() == 0

        response_payload = '{"embeddings": [[1.0, 2.0, 3.0]]}'
        with patch("urllib.request.urlopen") as mock_urlopen, patch("urllib.request.Request"):
            mock_resp = MagicMock()
            mock_resp.read.return_value = response_payload.encode()
            mock_urlopen.return_value.__enter__.return_value = mock_resp
            provider.embed(["text"])

        assert provider.dimensions() == 3

    def test_embed_network_error(self):
        provider = OllamaEmbeddingProvider()
        with patch("urllib.request.urlopen") as mock:
            mock.side_effect = OSError("connection refused")
            try:
                provider.embed(["hello"])
                raise AssertionError("expected EmbeddingError")
            except EmbeddingError:
                pass

    def test_embed_invalid_response(self):
        provider = OllamaEmbeddingProvider()
        response = "not json"

        with patch("urllib.request.urlopen") as mock_urlopen, patch("urllib.request.Request"):
            mock_resp = MagicMock()
            mock_resp.read.return_value = response.encode()
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            try:
                provider.embed(["hello"])
                raise AssertionError("expected EmbeddingError")
            except EmbeddingError:
                pass
