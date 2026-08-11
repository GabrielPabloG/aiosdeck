"""PricingResolver — calculate costs from normalized UsageRecord.

Versioned pricing table per (provider, model). Costs are computed at the
time of usage capture and persisted immutably via CostRecord (a snapshot,
not recalculated later when prices change).

v0.9.3 uses a hardcoded PRICING_V1 table. Future versions may load pricing
from files, APIs, or user configuration.
"""

from datetime import UTC, datetime

PRICING_V1: dict[tuple[str, str], dict] = {
    ("openai", "gpt-4o"): {"input_per_1M": 5.00, "output_per_1M": 15.00},
    ("openai", "gpt-4o-mini"): {"input_per_1M": 0.15, "output_per_1M": 0.60},
    ("openai", "gpt-4.1"): {"input_per_1M": 2.00, "output_per_1M": 8.00},
    ("openai", "gpt-4.1-mini"): {"input_per_1M": 0.40, "output_per_1M": 1.60},
    ("openai", "gpt-4.1-nano"): {"input_per_1M": 0.10, "output_per_1M": 0.40},
    ("anthropic", "claude-sonnet-4-20250514"): {"input_per_1M": 3.00, "output_per_1M": 15.00},
    ("anthropic", "claude-opus-4-20250514"): {"input_per_1M": 15.00, "output_per_1M": 75.00},
    ("anthropic", "claude-haiku-3-5"): {"input_per_1M": 0.80, "output_per_1M": 4.00},
    ("deepseek", "deepseek-chat"): {"input_per_1M": 0.27, "output_per_1M": 1.10},
    ("deepseek", "deepseek-reasoner"): {"input_per_1M": 0.55, "output_per_1M": 2.19},
    ("openrouter", "deepseek-v4-flash-0731"): {"input_per_1M": 0.08, "output_per_1M": 0.252},
    ("openrouter", "deepseek-v4-flash-latest"): {"input_per_1M": 0.08, "output_per_1M": 0.252},
    ("google", "gemini-2.5-flash"): {"input_per_1M": 0.15, "output_per_1M": 0.60},
    ("google", "gemini-2.5-pro"): {"input_per_1M": 1.25, "output_per_1M": 10.00},
}


class PricingResolver:
    name = "pricing"
    version = "v1"

    def __init__(self, version: str = "v1") -> None:
        tables: dict[str, dict] = {"v1": PRICING_V1}
        if version not in tables:
            raise ValueError(f"Unknown pricing version: {version}")
        self._pricing = tables[version]
        self._version = version

    def resolve(
        self,
        provider: str,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> dict:
        """Return a cost dictionary (ready for CostRecord persistence).

        Returns status="unpriced" when no pricing entry is found for the
        (provider, model) pair. Never guesses — missing data is acceptable.
        """
        key = (provider.strip().lower() if provider else "", model.strip().lower() if model else "")
        price = self._pricing.get(key) or self._pricing.get(self._normalize_key(key))
        if price is None or input_tokens is None or output_tokens is None:
            return {
                "input_cost": 0.0,
                "output_cost": 0.0,
                "total_cost": 0.0,
                "currency": "USD",
                "status": "unpriced",
                "pricing_version": self._version,
                "pricing_source": "builtin",
                "calculated_at": datetime.now(UTC).isoformat(),
            }

        input_cost = (input_tokens / 1_000_000) * price["input_per_1M"]
        output_cost = (output_tokens / 1_000_000) * price["output_per_1M"]

        return {
            "input_cost": round(input_cost, 6),
            "output_cost": round(output_cost, 6),
            "total_cost": round(input_cost + output_cost, 6),
            "currency": "USD",
            "status": "priced",
            "pricing_version": self._version,
            "pricing_source": "builtin",
            "calculated_at": datetime.now(UTC).isoformat(),
        }

    @staticmethod
    def _normalize_key(key: tuple[str, str]) -> tuple[str, str]:
        """Resolve OpenRouter routing aliases to a priced bare model name.

        The runtime records the full routed model id (e.g.
        ``openrouter/~deepseek/deepseek-v4-flash-latest``); the pricing table
        is keyed on the provider and the bare model name. This strips the
        OpenRouter ``~`` fallback marker and any provider/path prefix.
        """
        provider, model = key
        provider = provider.replace("~", "").strip()
        model = model.replace("~", "").strip()
        if "/" in model:
            model = model.rsplit("/", 1)[-1]
        return provider, model
