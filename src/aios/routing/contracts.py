"""Model routing contracts."""

from typing import Protocol, runtime_checkable

from aios.routing.models import RouteDecision, RouteInput


@runtime_checkable
class ModelRouter(Protocol):
    def route(self, input: RouteInput) -> RouteDecision: ...


@runtime_checkable
class ModelRanker(Protocol):
    def score(
        self,
        agent: str,
        candidates: list[dict],
        telemetry: object | None = None,
    ) -> list[tuple[str, float]]: ...
