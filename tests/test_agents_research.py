"""Tests for ResearchAgent — fetcher injection and delegation."""

import pytest

from aios.agents.research import ResearchAgent, ResearchResult


def test_research_agent_capabilities():
    assert "internet" in ResearchAgent.required_capabilities
    assert "shell" not in ResearchAgent.required_capabilities
    assert "filesystem_read" not in ResearchAgent.required_capabilities


def test_search_returns_fetcher_result():
    expected = ResearchResult(query="aios", summary="summary", sources=["https://x"])
    agent = ResearchAgent(fetcher=lambda query: expected)
    assert agent.search("aios") is expected


def test_search_passes_query_to_fetcher():
    received: list[str] = []

    def recording_fetcher(query):
        received.append(query)
        return ResearchResult(query=query, summary="", sources=[])

    agent = ResearchAgent(fetcher=recording_fetcher)
    agent.search("python agents")
    assert received == ["python agents"]


def test_search_propagates_fetcher_error():
    def failing_fetcher(query):
        raise RuntimeError("network down")

    agent = ResearchAgent(fetcher=failing_fetcher)
    with pytest.raises(RuntimeError, match="network down"):
        agent.search("anything")
