"""Rule-based model routing engine."""

from aios.config.schema import RouteConfig
from aios.routing.models import RouteDecision, RouteInput

_MODEL_PRICING: dict[str, float] = {
    "ollama/llama3": 0.0,
    "ollama/llama3:70b": 0.0,
    "ollama/codellama": 0.0,
    "anthropic/claude-haiku": 1.25,
    "anthropic/claude-sonnet": 3.0,
    "anthropic/claude-opus": 15.0,
    "openai/gpt-4o-mini": 0.15,
    "openai/gpt-4o": 2.5,
    "openrouter/deepseek/deepseek-v4-flash": 0.068,
    "openrouter/qwen/qwen3-coder": 0.22,
    "openrouter/openai/gpt-5-mini": 0.30,
    "openrouter/anthropic/claude-sonnet-4-5": 3.0,
}

_COMPLEXITY_VARIANT: dict[str, str] = {
    "high": "high",
    "medium": "",
    "low": "minimal",
}

_COMPLEXITY_TOKENS: dict[str, int] = {
    "high": 2000,
    "medium": 1000,
    "low": 500,
}


class RuleBasedRouter:
    name = "routing"

    def __init__(self, config: RouteConfig) -> None:
        self._config = config

    @property
    def config(self) -> RouteConfig:
        return self._config

    def route(self, input: RouteInput) -> RouteDecision:
        if input.model_override:
            return self._build_override_decision(input)

        for idx, rule in enumerate(self._config.rules):
            if self._rule_matches(rule, input):
                decision = self._build_decision_from_rule(rule, idx, input)
                decision = self._apply_cost_cap(input, decision, idx)
                return decision

        return self._build_default_decision(input)

    def _rule_matches(self, rule: dict, input: RouteInput) -> bool:
        rule_agent = rule.get("agent", "")
        if rule_agent and rule_agent != input.agent:
            return False

        rule_complexity = rule.get("complexity", "")
        if rule_complexity and rule_complexity != input.complexity:
            return False

        context_limit = self._config.context_limits.get(input.agent, 0)
        return not (context_limit and input.context_size > context_limit)

    def _build_override_decision(self, input: RouteInput) -> RouteDecision:
        provider, _, model_name = input.model_override.partition("/")
        if not model_name:
            model_name = provider
            provider = ""
        return RouteDecision(
            provider=provider or "unknown",
            model=input.model_override,
            reason="explicit_override",
            estimated_cost=self._estimate_cost(
                input.model_override, input.complexity, input.context_size
            ),
            source="override",
        )

    def _build_decision_from_rule(self, rule: dict, idx: int, input: RouteInput) -> RouteDecision:
        provider = rule.get("provider", self._config.default_provider)
        model = rule.get("model", self._config.default_model)
        variant = rule.get("variant", _COMPLEXITY_VARIANT.get(input.complexity, ""))
        model_id = self._model_id(provider, model)
        return RouteDecision(
            provider=provider,
            model=model_id,
            variant=variant,
            reason=f"policy:{idx}",
            estimated_cost=self._estimate_cost(model_id, input.complexity, input.context_size),
            fallback_chain=self._build_fallback_chain(provider),
        )

    def _build_default_decision(self, input: RouteInput) -> RouteDecision:
        provider = self._config.default_provider
        model = self._config.default_model
        variant = self._config.default_variant or _COMPLEXITY_VARIANT.get(input.complexity, "")
        model_id = self._model_id(provider, model)
        return RouteDecision(
            provider=provider,
            model=model_id,
            variant=variant,
            reason="heuristic:default",
            estimated_cost=self._estimate_cost(model_id, input.complexity, input.context_size),
            fallback_chain=self._build_fallback_chain(provider),
        )

    def _build_fallback_chain(self, current_provider: str) -> list[dict]:
        chain: list[dict] = []
        seen: set[str] = {current_provider}
        for fp in self._config.fallback_providers:
            p = fp.get("provider", "")
            if not p or p in seen:
                continue
            model = fp.get("model", self._config.default_model)
            chain.append(
                {
                    "provider": p,
                    "model": self._model_id(p, model),
                    "variant": fp.get("variant", ""),
                }
            )
            seen.add(p)
        return chain

    def _apply_cost_cap(
        self, input: RouteInput, decision: RouteDecision, rule_idx: int
    ) -> RouteDecision:
        cap = self._config.cost_cap
        if cap <= 0 or decision.estimated_cost <= cap:
            return decision

        chain = decision.fallback_chain[:]
        for fb in chain:
            model_id = fb["model"]
            cost = self._estimate_cost(model_id, input.complexity, input.context_size)
            if cost <= cap:
                return RouteDecision(
                    provider=fb["provider"],
                    model=model_id,
                    variant=fb.get("variant", decision.variant),
                    reason=f"policy:{rule_idx}+cost_cap",
                    estimated_cost=cost,
                    fallback_chain=[c for c in chain if c["provider"] != fb["provider"]],
                )

        raise RuntimeError(
            f"Cost cap ${cap:.2f} exceeded: "
            f"model {decision.model} costs ${decision.estimated_cost:.4f}, "
            f"and no fallback provider fits the budget"
        )

    @staticmethod
    def _estimate_cost(model_id: str, complexity: str, context_size: int) -> float:
        input_price = _MODEL_PRICING.get(model_id, _MODEL_PRICING.get("ollama/llama3", 0.0))
        if input_price == 0.0:
            return 0.0
        input_tokens = max(context_size, 1) * 4
        output_tokens = _COMPLEXITY_TOKENS.get(complexity, 1000)
        return (input_price * input_tokens + input_price * 3 * output_tokens) / 1_000_000

    @staticmethod
    def _model_id(provider: str, model: str) -> str:
        if "/" in model:
            return model
        return f"{provider}/{model}"

    def initialize(self) -> None:
        pass

    def health_check(self) -> bool:
        return True

    def shutdown(self) -> None:
        pass
