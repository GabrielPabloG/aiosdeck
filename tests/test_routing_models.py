"""Tests for routing models and contracts."""

import json

from aios.routing import ModelRanker, ModelRouter, RouteDecision, RouteInput


class TestRouteInput:
    def test_defaults(self):
        inp = RouteInput(agent="planner")
        assert inp.task_type == "code"
        assert inp.complexity == "medium"
        assert inp.context_size == 0
        assert inp.budget_token == 3000
        assert inp.model_override == ""

    def test_full_init(self):
        inp = RouteInput(
            agent="developer",
            task_type="test",
            complexity="high",
            context_size=12000,
            budget_token=8000,
            model_override="anthropic/claude-sonnet",
        )
        assert inp.agent == "developer"
        assert inp.task_type == "test"
        assert inp.complexity == "high"
        assert inp.context_size == 12000
        assert inp.budget_token == 8000
        assert inp.model_override == "anthropic/claude-sonnet"


class TestRouteDecision:
    def test_defaults(self):
        decision = RouteDecision(provider="ollama", model="llama3")
        assert decision.variant == ""
        assert decision.reason == ""
        assert decision.estimated_cost == 0.0
        assert decision.fallback_chain == []
        assert decision.source == "router"

    def test_full_init(self):
        decision = RouteDecision(
            provider="anthropic",
            model="anthropic/claude-sonnet",
            variant="high",
            reason="policy:planner_high",
            estimated_cost=0.15,
            fallback_chain=[
                {"provider": "ollama", "model": "llama3", "variant": ""},
            ],
            source="override",
        )
        assert decision.provider == "anthropic"
        assert decision.model == "anthropic/claude-sonnet"
        assert decision.variant == "high"
        assert decision.reason == "policy:planner_high"
        assert decision.estimated_cost == 0.15
        assert len(decision.fallback_chain) == 1
        assert decision.fallback_chain[0]["provider"] == "ollama"
        assert decision.source == "override"

    def test_serializable(self):
        decision = RouteDecision(
            provider="ollama",
            model="ollama/llama3",
            variant="high",
            reason="policy:0",
            estimated_cost=0.0,
            fallback_chain=[
                {"provider": "anthropic", "model": "anthropic/claude-haiku", "variant": ""}
            ],
            source="router",
        )
        d = {
            "provider": decision.provider,
            "model": decision.model,
            "variant": decision.variant,
            "reason": decision.reason,
            "estimated_cost": decision.estimated_cost,
            "fallback_chain": decision.fallback_chain,
            "source": decision.source,
        }
        assert json.loads(json.dumps(d)) == d


class TestModelRouterProtocol:
    def test_is_protocol(self):
        class FakeRouter:
            def route(self, input: RouteInput) -> RouteDecision:
                return RouteDecision(provider="ollama", model="llama3")

        assert isinstance(FakeRouter(), ModelRouter)

    def test_missing_route_not_router(self):
        class NotRouter:
            pass

        assert not isinstance(NotRouter(), ModelRouter)


class TestModelRankerProtocol:
    def test_is_protocol(self):
        class FakeRanker:
            def score(self, agent, candidates, telemetry=None):
                return []

        assert isinstance(FakeRanker(), ModelRanker)
