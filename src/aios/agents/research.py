"""Minimal ResearchAgent scaffold.

Responsibilities:
- Provide an interface for performing searches and returning structured summaries.
- The agent is designed for dependency injection of a fetcher (to enable mocking in CI/tests).

The agent never performs HTTP calls itself; it delegates entirely to an
injected fetcher. The fetcher is a required dependency, optional in the
constructor only to ease dependency injection and testing.
"""

from collections.abc import Callable
from dataclasses import dataclass

from aios.agents.base import BaseAgent


@dataclass
class ResearchResult:
    query: str
    summary: str
    sources: list[str]


class ResearchAgent(BaseAgent):
    name = "research"
    required_capabilities = ["internet"]
    required_skills: list[str] = []

    def __init__(
        self,
        fetcher: Callable[[str], ResearchResult] | None = None,
    ) -> None:
        self._fetcher = fetcher

    def search(self, query: str) -> ResearchResult:
        if self._fetcher is None:
            raise ValueError("ResearchAgent requires an injected fetcher")
        return self._fetcher(query)
