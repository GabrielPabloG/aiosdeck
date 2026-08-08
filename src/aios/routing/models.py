"""Routing data models."""

from dataclasses import dataclass, field


@dataclass
class RouteInput:
    agent: str
    task_type: str = "code"
    complexity: str = "medium"
    context_size: int = 0
    budget_token: int = 3000
    model_override: str = ""


@dataclass
class RouteDecision:
    provider: str
    model: str
    variant: str = ""
    reason: str = ""
    estimated_cost: float = 0.0
    fallback_chain: list[dict] = field(default_factory=list)
    source: str = "router"
