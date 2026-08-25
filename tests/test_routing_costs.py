"""Cost estimation and cost-cap contracts for RuleBasedRouter."""

import pytest

from aios.config.schema import RouteConfig
from aios.routing.engine import RuleBasedRouter
from aios.routing.models import RouteDecision, RouteInput


def _router(**kwargs) -> RuleBasedRouter:
    return RuleBasedRouter(
        RouteConfig(default_provider="ollama", default_model="llama3", **kwargs)
    )


class TestEstimateCost:
    @pytest.mark.parametrize(
        ("model_id", "complexity", "context_size", "expected"),
        [
            ("anthropic/claude-haiku", "medium", 10000, 0.05375),
            ("anthropic/claude-haiku", "low", 10000, 0.051875),
            ("anthropic/claude-opus", "high", 10000, 0.69),
            ("openai/gpt-4o-mini", "medium", 10000, 0.00645),
            ("~openrouter/deepseek/deepseek-v4-flash-latest", "medium", 10000, 0.00344),
            ("anthropic/claude-haiku", "extreme", 10000, 0.05375),
        ],
    )
    def test_matches_price_times_tokens_formula(self, model_id, complexity, context_size, expected):
        assert (
            RuleBasedRouter._estimate_cost(model_id, complexity, context_size)
            == pytest.approx(expected, rel=1e-9)
        )

    def test_context_floor_of_one(self):
        cost = RuleBasedRouter._estimate_cost("anthropic/claude-haiku", "high", 1)
        assert cost == pytest.approx((1.25 * 4 + 1.25 * 3 * 2000) / 1_000_000, rel=1e-9)

    @pytest.mark.parametrize(
        ("model_id", "complexity", "context_size"),
        [
            ("totally/unknown", "medium", 10000),
            ("ollama/llama3", "high", 999999),
            ("", "low", 0),
        ],
    )
    def test_free_models_cost_zero(self, model_id, complexity, context_size):
        assert RuleBasedRouter._estimate_cost(model_id, complexity, context_size) == 0.0


class TestModelId:
    def test_keeps_provider_namespaced_slug_without_registration(self):
        assert RuleBasedRouter._model_id("acme", "acme/M1", set()) == "acme/M1"

    def test_prefixes_plain_models(self):
        assert RuleBasedRouter._model_id("acme", "M1", set()) == "acme/M1"

    def test_prefixes_foreign_namespace(self):
        assert RuleBasedRouter._model_id("ollama", "corp/M9", {"ollama"}) == "ollama/corp/M9"


class TestCostCapBoundaries:
    def test_primary_cost_equal_to_cap_is_kept(self):
        cap = RuleBasedRouter._estimate_cost("anthropic/claude-haiku", "medium", 1000)
        router = _router(
            cost_cap=cap,
            rules=[
                {"agent": "planner", "provider": "anthropic", "model": "claude-haiku"},
            ],
            fallback_providers=[{"provider": "ollama", "model": "llama3"}],
        )
        decision = router.route(
            RouteInput(agent="planner", complexity="medium", context_size=1000)
        )
        assert decision.provider == "anthropic"
        assert decision.reason == "policy:0"

    def test_fallback_cost_equal_to_cap_is_chosen(self):
        cap = RuleBasedRouter._estimate_cost("anthropic/claude-haiku", "high", 1000)
        router = _router(
            cost_cap=cap,
            rules=[
                {
                    "agent": "planner",
                    "complexity": "high",
                    "provider": "openai",
                    "model": "gpt-4o",
                },
            ],
            fallback_providers=[{"provider": "anthropic", "model": "claude-haiku"}],
        )
        decision = router.route(
            RouteInput(agent="planner", complexity="high", context_size=1000)
        )
        assert decision.model == "anthropic/claude-haiku"
        assert decision.reason == "policy:0+cost_cap"

    def test_high_complexity_fallback_above_cap_raises(self):
        router = _router(
            cost_cap=0.01,
            rules=[
                {
                    "agent": "planner",
                    "complexity": "high",
                    "provider": "anthropic",
                    "model": "claude-sonnet",
                },
            ],
            fallback_providers=[{"provider": "anthropic", "model": "claude-haiku"}],
        )
        with pytest.raises(RuntimeError, match="Cost cap"):
            router.route(RouteInput(agent="planner", complexity="high", context_size=1000))


class TestCappedDecisionContract:
    def test_variant_chain_and_cost_of_capped_decision(self):
        router = _router(
            cost_cap=0.02,
            rules=[
                {
                    "agent": "planner",
                    "complexity": "high",
                    "provider": "anthropic",
                    "model": "claude-sonnet",
                },
            ],
        )
        capped = RouteDecision(
            provider="anthropic",
            model="anthropic/claude-sonnet",
            variant="high",
            reason="policy:0",
            estimated_cost=0.03,
            fallback_chain=[
                {"provider": "openai", "model": "openai/gpt-4o-mini"},
                {"provider": "ollama", "model": "ollama/llama3", "variant": ""},
            ],
        )

        result = router._apply_cost_cap(
            RouteInput(agent="planner", complexity="high", context_size=1000), capped, 0
        )

        assert result.provider == "openai"
        assert result.model == "openai/gpt-4o-mini"
        assert result.variant == "high"
        assert result.reason == "policy:0+cost_cap"
        assert result.estimated_cost == pytest.approx(0.0015, rel=1e-9)
        assert result.fallback_chain == [
            {"provider": "ollama", "model": "ollama/llama3", "variant": ""}
        ]


class TestHeuristicDefaultContract:
    def test_variant_chain_and_model_of_default_decision(self):
        router = _router(
            fallback_providers=[
                {"model": "x9"},
                {"provider": "ollama"},
                {"provider": "zenith"},
                {"provider": "acme", "model": "a/b"},
            ],
        )
        decision = router.route(RouteInput(agent="nobody", complexity="low"))

        assert decision.variant == "minimal"
        assert decision.model == "ollama/llama3"
        assert decision.fallback_chain == [
            {"provider": "zenith", "model": "zenith/llama3", "variant": ""},
            {"provider": "acme", "model": "acme/a/b", "variant": ""},
        ]

    def test_registered_namespaced_default_model_is_kept(self):
        router = RuleBasedRouter(
            RouteConfig(
                default_provider="ollama",
                default_model="zenith/z9",
                fallback_providers=[{"provider": "zenith", "model": "z9"}],
            )
        )
        decision = router.route(RouteInput(agent="nobody"))
        assert decision.model == "zenith/z9"

    def test_default_variant_empty_for_unmapped_complexity(self):
        decision = _router().route(RouteInput(agent="nobody", complexity="extreme"))
        assert decision.variant == ""

    def test_priced_default_cost_uses_complexity_tokens(self):
        router = RuleBasedRouter(
            RouteConfig(default_provider="anthropic", default_model="claude-haiku")
        )
        decision = router.route(
            RouteInput(agent="nobody", complexity="high", context_size=10000)
        )
        assert decision.estimated_cost == pytest.approx(0.0575, rel=1e-9)


class TestRuleMatchedContract:
    def test_priced_rule_cost_uses_complexity_tokens(self):
        config = RouteConfig(
            default_provider="anthropic",
            default_model="claude-haiku",
            rules=[{"agent": "planner", "complexity": "high"}],
        )
        decision = RuleBasedRouter(config).route(
            RouteInput(agent="planner", complexity="high", context_size=10000)
        )
        assert decision.estimated_cost == pytest.approx(0.0575, rel=1e-9)

    def test_fallback_chain_excludes_rule_provider(self):
        config = RouteConfig(
            default_provider="ollama",
            default_model="llama3",
            rules=[
                {
                    "agent": "dev",
                    "provider": "acme",
                    "model": "acme/m1",
                    "complexity": "low",
                },
            ],
            fallback_providers=[
                {"provider": "acme", "model": "m2"},
                {"provider": "ollama", "model": "llama3"},
            ],
        )
        decision = RuleBasedRouter(config).route(RouteInput(agent="dev", complexity="low"))
        assert [entry["provider"] for entry in decision.fallback_chain] == ["ollama"]
