"""Tests for the rule-based routing engine."""

import pytest

from aios.config.schema import RouteConfig
from aios.routing.engine import RuleBasedRouter
from aios.routing.models import RouteInput


def _basic_config() -> RouteConfig:
    return RouteConfig(
        default_provider="ollama",
        default_model="llama3",
        rules=[
            {
                "agent": "planner",
                "complexity": "high",
                "provider": "anthropic",
                "model": "claude-sonnet",
            },
            {
                "agent": "planner",
                "complexity": "medium",
                "provider": "ollama",
                "model": "llama3:70b",
            },
            {
                "agent": "developer",
                "complexity": "low",
                "provider": "ollama",
                "model": "codellama",
            },
        ],
        fallback_providers=[
            {"provider": "ollama", "model": "llama3"},
        ],
    )


class TestRuleBasedRouter:
    def test_override_explicit_audits(self):
        router = RuleBasedRouter(_basic_config())
        decision = router.route(
            RouteInput(agent="planner", task_type="plan", model_override="anthropic/claude-opus")
        )
        assert decision.source == "override"
        assert decision.reason == "explicit_override"
        assert decision.model == "anthropic/claude-opus"
        assert decision.provider == "anthropic"
        assert decision.estimated_cost > 0

    def test_override_with_single_token(self):
        router = RuleBasedRouter(_basic_config())
        decision = router.route(RouteInput(agent="planner", model_override="llama3"))
        assert decision.source == "override"
        assert decision.model == "llama3"

    def test_match_by_agent_and_complexity(self):
        router = RuleBasedRouter(_basic_config())
        decision = router.route(RouteInput(agent="planner", task_type="plan", complexity="high"))
        assert decision.source == "router"
        assert decision.reason == "policy:0"
        assert decision.provider == "anthropic"
        assert decision.model == "anthropic/claude-sonnet"

    def test_match_second_rule(self):
        router = RuleBasedRouter(_basic_config())
        decision = router.route(RouteInput(agent="planner", task_type="plan", complexity="medium"))
        assert decision.reason == "policy:1"
        assert decision.provider == "ollama"
        assert decision.model == "ollama/llama3:70b"

    def test_match_developer_low(self):
        router = RuleBasedRouter(_basic_config())
        decision = router.route(RouteInput(agent="developer", task_type="code", complexity="low"))
        assert decision.reason == "policy:2"
        assert decision.model == "ollama/codellama"

    def test_no_match_falls_back_to_default(self):
        router = RuleBasedRouter(_basic_config())
        decision = router.route(RouteInput(agent="developer", task_type="code", complexity="high"))
        assert decision.reason == "heuristic:default"
        assert decision.provider == "ollama"
        assert decision.model == "ollama/llama3"

    def test_fallback_chain_generated(self):
        router = RuleBasedRouter(_basic_config())
        decision = router.route(RouteInput(agent="planner", task_type="plan", complexity="high"))
        assert len(decision.fallback_chain) >= 1
        assert decision.fallback_chain[0]["provider"] == "ollama"

    def test_cost_cap_blocks_and_forces_cheaper(self):
        config = RouteConfig(
            default_provider="ollama",
            default_model="llama3",
            cost_cap=0.001,
            rules=[
                {
                    "agent": "planner",
                    "complexity": "high",
                    "provider": "anthropic",
                    "model": "claude-sonnet",
                },
            ],
            fallback_providers=[
                {"provider": "ollama", "model": "llama3"},
            ],
        )
        router = RuleBasedRouter(config)
        decision = router.route(
            RouteInput(agent="planner", task_type="plan", complexity="high", context_size=12000)
        )
        assert decision.provider == "ollama"
        assert decision.reason == "policy:0+cost_cap"
        assert decision.estimated_cost <= config.cost_cap

    def test_cost_cap_exhausted_raises(self):
        config = RouteConfig(
            cost_cap=0.0001,
            rules=[
                {
                    "agent": "developer",
                    "complexity": "high",
                    "provider": "anthropic",
                    "model": "claude-sonnet",
                },
            ],
            fallback_providers=[
                {"provider": "anthropic", "model": "claude-opus"},
            ],
        )
        router = RuleBasedRouter(config)
        with pytest.raises(RuntimeError, match="Cost cap"):
            router.route(
                RouteInput(
                    agent="developer", task_type="code", complexity="high", context_size=50000
                )
            )

    def test_context_limit_enforced(self):
        config = RouteConfig(
            default_provider="ollama",
            default_model="llama3",
            context_limits={"planner": 100},
            rules=[
                {
                    "agent": "planner",
                    "complexity": "high",
                    "provider": "anthropic",
                    "model": "claude-sonnet",
                },
            ],
        )
        router = RuleBasedRouter(config)
        decision = router.route(
            RouteInput(agent="planner", task_type="plan", complexity="high", context_size=1000)
        )
        assert decision.reason == "heuristic:default"

    def test_estimated_cost_zero_for_local(self):
        router = RuleBasedRouter(_basic_config())
        decision = router.route(RouteInput(agent="planner", task_type="plan", complexity="medium"))
        assert decision.estimated_cost == 0.0

    def test_variant_set_for_complexity(self):
        router = RuleBasedRouter(_basic_config())
        decision_high = router.route(
            RouteInput(agent="planner", task_type="plan", complexity="high")
        )
        assert decision_high.variant == "high"

        decision_low = router.route(
            RouteInput(agent="developer", task_type="code", complexity="low")
        )
        assert decision_low.variant == "minimal"

    def test_empty_rules_falls_back(self):
        config = RouteConfig(default_provider="ollama", default_model="llama3")
        router = RuleBasedRouter(config)
        decision = router.route(RouteInput(agent="planner"))
        assert decision.reason == "heuristic:default"
        assert decision.model == "ollama/llama3"

    def test_fallback_chain_deduplicates(self):
        config = RouteConfig(
            default_provider="ollama",
            default_model="llama3",
            rules=[
                {
                    "agent": "planner",
                    "provider": "anthropic",
                    "model": "claude-sonnet",
                },
            ],
            fallback_providers=[
                {"provider": "ollama", "model": "llama3"},
                {"provider": "ollama", "model": "llama3:70b"},
            ],
        )
        router = RuleBasedRouter(config)
        decision = router.route(RouteInput(agent="planner"))
        providers = [f["provider"] for f in decision.fallback_chain]
        assert providers.count("ollama") == 1


_OPENROUTER_SLUGS = [
    "openrouter/deepseek/deepseek-v4-flash",
    "openrouter/qwen/qwen3-coder",
    "openrouter/openai/gpt-5-mini",
    "openrouter/anthropic/claude-sonnet-4-5",
]


class TestOpenRouterPricing:
    """OpenRouter models are priced (estimated_cost > 0) and cappable."""

    @pytest.mark.parametrize("slug", _OPENROUTER_SLUGS)
    def test_openrouter_slug_has_cost(self, slug: str) -> None:
        config = RouteConfig(
            default_provider="ollama",
            default_model="llama3",
            rules=[{"agent": "planner", "model": slug}],
        )
        decision = RuleBasedRouter(config).route(
            RouteInput(agent="planner", complexity="medium", context_size=10000)
        )
        assert decision.estimated_cost > 0

    def test_cost_cap_forces_cheap_openrouter_fallback(self) -> None:
        config = RouteConfig(
            default_provider="ollama",
            default_model="llama3",
            cost_cap=0.001,
            rules=[
                {
                    "agent": "planner",
                    "complexity": "high",
                    "provider": "anthropic",
                    "model": "openrouter/anthropic/claude-sonnet-4-5",
                },
            ],
            fallback_providers=[{"provider": "ollama", "model": "llama3"}],
        )
        decision = RuleBasedRouter(config).route(
            RouteInput(agent="planner", complexity="high", context_size=20000)
        )
        assert decision.provider == "ollama"
        assert decision.model == "ollama/llama3"
        assert decision.reason == "policy:0+cost_cap"
        assert decision.estimated_cost <= config.cost_cap

    def test_openrouter_explicit_variant_preserved(self) -> None:
        config = RouteConfig(
            default_provider="ollama",
            default_model="llama3",
            rules=[
                {
                    "agent": "planner",
                    "model": "openrouter/qwen/qwen3-coder",
                    "variant": "official",
                },
            ],
        )
        decision = RuleBasedRouter(config).route(RouteInput(agent="planner"))
        assert decision.variant == "official"
        assert decision.model == "openrouter/qwen/qwen3-coder"
        assert decision.estimated_cost > 0

    def test_default_ollama_llama3_still_free(self) -> None:
        config = RouteConfig(default_provider="ollama", default_model="llama3")
        decision = RuleBasedRouter(config).route(RouteInput(agent="planner"))
        assert decision.model == "ollama/llama3"
        assert decision.estimated_cost == 0.0
