"""Tests for UsageRecord — normalization and provider_raw sanitization."""

from aios.usage.models import UsageRecord, sanitize_provider_raw


class TestUsageRecordFromProvider:
    def test_openai_payload(self):
        record = UsageRecord.from_provider(
            {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
            provider="openai",
            agent="planner",
            model="gpt-4o",
        )
        assert record.input_tokens == 100
        assert record.output_tokens == 50
        assert record.total_tokens == 150
        assert record.provider == "openai"
        assert record.agent == "planner"
        assert record.model == "gpt-4o"

    def test_ollama_prompt_eval(self):
        record = UsageRecord.from_provider(
            {"prompt_eval_count": 200, "eval_count": 80},
            provider="ollama",
            agent="developer",
            model="llama3",
        )
        assert record.input_tokens == 200
        assert record.output_tokens == 80
        assert record.provider == "ollama"

    def test_deepseek_prompt_tokens(self):
        record = UsageRecord.from_provider(
            {"prompt_tokens": 300, "completion_tokens": 120},
            provider="deepseek",
            agent="reviewer",
            model="deepseek-chat",
        )
        assert record.input_tokens == 300
        assert record.output_tokens == 120
        assert record.provider == "deepseek"

    def test_missing_fields_are_none(self):
        record = UsageRecord.from_provider(
            {"input_tokens": 10},
            provider="minimal",
            agent="tester",
        )
        assert record.input_tokens == 10
        assert record.output_tokens is None
        assert record.total_tokens is None
        assert record.cached_tokens is None
        assert record.reasoning_tokens is None
        assert record.context_tokens is None

    def test_empty_payload(self):
        record = UsageRecord.from_provider({}, provider="empty", agent="test")
        assert record.input_tokens is None
        assert record.output_tokens is None
        assert record.has_any_tokens is False

    def test_cached_tokens_from_anthropic(self):
        record = UsageRecord.from_provider(
            {"input_tokens": 400, "output_tokens": 200, "cache_read_input_tokens": 100},
            provider="anthropic",
            agent="planner",
        )
        assert record.cached_tokens == 100

    def test_total_tokens_fallback_total_count(self):
        record = UsageRecord.from_provider(
            {"prompt_tokens": 10, "completion_tokens": 5, "total_count": 15},
            provider="custom",
        )
        assert record.total_tokens == 15

    def test_context_tokens_preserved(self):
        record = UsageRecord.from_provider(
            {"input_tokens": 10, "context_tokens": 500},
            provider="rag",
        )
        assert record.context_tokens == 500

    def test_has_any_tokens_true(self):
        record = UsageRecord(input_tokens=1)
        assert record.has_any_tokens is True

    def test_has_any_tokens_false(self):
        record = UsageRecord()
        assert record.has_any_tokens is False


class TestSanitizeProviderRaw:
    def test_none_returns_none(self):
        assert sanitize_provider_raw(None) is None

    def test_removes_prompt(self):
        result = sanitize_provider_raw({"prompt": "secret text", "model": "gpt-4o"})
        assert result["prompt"] == "[redacted]"
        assert result["model"] == "gpt-4o"

    def test_removes_messages(self):
        result = sanitize_provider_raw({"messages": [{"role": "user"}]})
        assert result["messages"] == "[redacted]"

    def test_removes_api_key(self):
        result = sanitize_provider_raw({"api_key": "sk-abc123"})
        assert result["api_key"] == "[redacted]"

    def test_removes_token(self):
        result = sanitize_provider_raw({"token": "xyz789"})
        assert result["token"] == "[redacted]"

    def test_removes_secret(self):
        result = sanitize_provider_raw({"secret": "sssh"})
        assert result["secret"] == "[redacted]"

    def test_removes_authorization(self):
        result = sanitize_provider_raw({"authorization": "Bearer xyz"})
        assert result["authorization"] == "[redacted]"

    def test_removes_key_substring(self):
        result = sanitize_provider_raw({"my_api_key_name": "sk-123"})
        assert result["my_api_key_name"] == "[redacted]"

    def test_preserves_safe_keys(self):
        result = sanitize_provider_raw({"model": "gpt-4o", "usage": 42, "id": "abc"})
        assert result["model"] == "gpt-4o"
        assert result["usage"] == 42
        assert result["id"] == "abc"


class TestUsageRecordToDict:
    def test_to_dict_includes_all_fields(self):
        record = UsageRecord(input_tokens=100, output_tokens=50, agent="planner")
        d = record.to_dict()
        assert d["input_tokens"] == 100
        assert d["output_tokens"] == 50
        assert d["agent"] == "planner"
        assert "context_tokens" in d
