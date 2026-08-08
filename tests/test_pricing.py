"""Tests for PricingResolver — cost calculation and unpriced fallback."""

from aios.telemetry.pricing import PRICING_V1, PricingResolver


class TestPricingResolver:
    def test_resolve_gpt4o(self):
        resolver = PricingResolver(version="v1")
        cost = resolver.resolve("openai", "gpt-4o", 1000, 500)
        assert cost["status"] == "priced"
        assert cost["pricing_source"] == "builtin"
        assert cost["pricing_version"] == "v1"
        assert cost["currency"] == "USD"
        expected_input = (1000 / 1_000_000) * 5.00
        expected_output = (500 / 1_000_000) * 15.00
        assert cost["input_cost"] == round(expected_input, 6)
        assert cost["output_cost"] == round(expected_output, 6)
        assert cost["total_cost"] == round(expected_input + expected_output, 6)

    def test_resolve_deepseek(self):
        resolver = PricingResolver(version="v1")
        cost = resolver.resolve("deepseek", "deepseek-chat", 1000000, 500000)
        assert cost["status"] == "priced"
        expected_input = 1.0 * 0.27
        expected_output = 0.5 * 1.10
        assert round(cost["total_cost"], 6) == round(expected_input + expected_output, 6)

    def test_resolve_case_insensitive(self):
        resolver = PricingResolver(version="v1")
        cost = resolver.resolve("OpenAI", "GPT-4o", 1000, 500)
        assert cost["status"] == "priced"

    def test_unpriced_unknown_model(self):
        resolver = PricingResolver(version="v1")
        cost = resolver.resolve("unknown", "unknown-model", 1000, 500)
        assert cost["status"] == "unpriced"
        assert cost["total_cost"] == 0.0

    def test_unpriced_missing_tokens(self):
        resolver = PricingResolver(version="v1")
        cost = resolver.resolve("openai", "gpt-4o", None, None)
        assert cost["status"] == "unpriced"

    def test_unpriced_partial_tokens(self):
        resolver = PricingResolver(version="v1")
        cost = resolver.resolve("openai", "gpt-4o", 100, None)
        assert cost["status"] == "unpriced"

    def test_unknown_pricing_version(self):
        try:
            PricingResolver(version="v999")
            raise AssertionError("Should have raised ValueError")
        except ValueError:
            pass

    def test_resolve_claude_opus(self):
        resolver = PricingResolver(version="v1")
        cost = resolver.resolve("anthropic", "claude-opus-4-20250514", 1_000_000, 500_000)
        assert cost["status"] == "priced"
        assert round(cost["total_cost"], 6) == round(15.00 + 37.50, 6)


class TestPricingTableCoverage:
    def test_v1_table_has_entries(self):
        assert len(PRICING_V1) > 0
        assert ("openai", "gpt-4o") in PRICING_V1
        assert ("deepseek", "deepseek-chat") in PRICING_V1
        assert ("anthropic", "claude-sonnet-4-20250514") in PRICING_V1
