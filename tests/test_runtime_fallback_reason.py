"""Unit tests for RuntimeEngine._fallback_reason static method."""

from aios.runtime import RuntimeEngine


class TestFallbackReason:
    def test_timeout_error_returns_timeout(self):
        error = TimeoutError("request timed out")
        assert RuntimeEngine._fallback_reason(error) == "timeout"

    def test_budget_error_returns_budget_exceeded(self):
        error = Exception("budget exceeded for model")
        assert RuntimeEngine._fallback_reason(error) == "budget_exceeded"

    def test_generic_error_returns_unavailable(self):
        error = Exception("connection refused")
        assert RuntimeEngine._fallback_reason(error) == "unavailable"

    def test_none_returns_empty_string(self):
        assert RuntimeEngine._fallback_reason(None) == ""
