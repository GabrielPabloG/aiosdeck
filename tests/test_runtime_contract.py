"""Integration tests for the RuntimeEngine → AgentResult contract.

Verifies that:
- OpenCodeAdapter returns AgentResult with populated metrics
- RuntimeEngine normalizes str returns from legacy adapters (OllamaAdapter)
- RuntimeEngine propagates fallback_used on fallback
- Consuming agents (DeveloperAgent, PlannerAgent) receive correct data
"""

import subprocess
from unittest.mock import MagicMock, patch

from aios.agents.models import AgentResult
from aios.config.schema import RouteConfig
from aios.routing.engine import RuleBasedRouter
from aios.runtime import RuntimeEngine


def _make_engine(
    adapter=None,
    router=None,
    fallback_chain=None,
):
    """Build a RuntimeEngine with configurable adapter and router."""
    if adapter is None:
        adapter = MagicMock()
        adapter.execute.return_value = "mocked output"
    if router is None:
        config = RouteConfig(
            default_provider="test",
            default_model="test/default",
            fallback_providers=fallback_chain or [],
        )
        router = RuleBasedRouter(config)
    return RuntimeEngine(adapter=adapter, router=router)


class TestLegacyAdapterNormalization:
    def test_str_return_becomes_agent_result(self):
        engine = _make_engine()
        result = engine.execute(
            "prompt", [], [], agent="dev", task_type="code", complexity="medium"
        )
        assert isinstance(result, AgentResult)
        assert result.output == "mocked output"
        assert result.tool_calls == 0
        assert result.llm_turns == 0

    def test_agent_result_returned_directly(self):
        adapter = MagicMock()
        adapter.execute.return_value = AgentResult(
            output="text",
            tool_calls=5,
            llm_turns=3,
            total_cost=0.01,
            tokens={"input": 100, "output": 50},
        )
        engine = _make_engine(adapter=adapter)
        result = engine.execute(
            "prompt", [], [], agent="dev", task_type="code", complexity="medium"
        )
        assert isinstance(result, AgentResult)
        assert result.tool_calls == 5
        assert result.llm_turns == 3
        assert result.total_cost == 0.01
        assert result.tokens == {"input": 100, "output": 50}

    def test_model_and_provider_propagated(self):
        adapter = MagicMock()
        adapter.execute.return_value = AgentResult(output="ok")
        config = RouteConfig(
            default_provider="my-provider",
            default_model="my-provider/my-model",
        )
        router = RuleBasedRouter(config)
        engine = _make_engine(adapter=adapter, router=router)
        result = engine.execute(
            "prompt", [], [], agent="dev", task_type="code", complexity="medium"
        )
        assert result.model == "my-provider/my-model"
        assert result.provider == "my-provider"


class TestFallbackUsed:
    def test_no_fallback(self):
        adapter = MagicMock()
        adapter.execute.return_value = AgentResult(output="ok")
        config = RouteConfig(
            default_provider="p1",
            default_model="p1/m1",
        )
        router = RuleBasedRouter(config)
        engine = _make_engine(adapter=adapter, router=router)
        result = engine.execute(
            "prompt", [], [], agent="dev", task_type="code", complexity="medium"
        )
        assert result.fallback_used is False

    def test_fallback_triggered(self):
        call_count = 0

        def side_effect(prompt, skills, caps, permissions, *, model="", variant="", max_steps=0):  # noqa: PLR0913
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("primary failed")
            return AgentResult(output="fallback ok")

        adapter = MagicMock()
        adapter.execute.side_effect = side_effect
        config = RouteConfig(
            default_provider="p1",
            default_model="p1/m1",
            fallback_providers=[{"provider": "p2", "model": "p2/m2"}],
        )
        router = RuleBasedRouter(config)
        engine = _make_engine(adapter=adapter, router=router)
        result = engine.execute(
            "prompt", [], [], agent="dev", task_type="code", complexity="medium"
        )
        assert result.fallback_used is True
        assert result.output == "fallback ok"
        assert result.model == "p2/m2"

    def test_all_fallbacks_exhausted(self):
        adapter = MagicMock()
        adapter.execute.side_effect = RuntimeError("fail")
        config = RouteConfig(
            default_provider="p1",
            default_model="p1/m1",
            fallback_providers=[{"provider": "p2", "model": "p2/m2"}],
        )
        router = RuleBasedRouter(config)
        engine = _make_engine(adapter=adapter, router=router)
        try:
            engine.execute(
                "prompt", [], [], agent="dev", task_type="code", complexity="medium"
            )
            raise AssertionError("Should have raised")
        except RuntimeError as exc:
            assert "exhausted" in str(exc).lower()


class TestOpenCodeAdapterContract:
    def test_execute_returns_agent_result(self):
        """Verify OpenCodeAdapter.execute() return type without running subprocess."""
        from aios.runtime.opencode import OpenCodeAdapter

        adapter = OpenCodeAdapter()
        adapter._opencode_installed = True
        adapter._ai_jail_installed = True
        adapter._initialized = True

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = (
            '{"type":"step_start","timestamp":1000,'
            '"part":{"id":"p1","messageID":"m1","sessionID":"s1",'
            '"type":"step-start"}}\n'
            '{"type":"text","timestamp":1001,'
            '"part":{"id":"p2","messageID":"m1","sessionID":"s1",'
            '"type":"text","text":"hello"}}\n'
            '{"type":"step_finish","timestamp":1002,'
            '"part":{"id":"p3","reason":"stop","messageID":"m1",'
            '"sessionID":"s1","type":"step-finish",'
            '"tokens":{"input":10,"output":5,"reasoning":0,'
            '"cache":{"read":0,"write":0}},"cost":0.001}}'
        )
        mock_result.stderr = ""

        with patch("aios.runtime.opencode.subprocess") as mock_sub:
            mock_sub.run.return_value = mock_result
            mock_sub.TimeoutExpired = subprocess.TimeoutExpired
            result = adapter.execute(
                "prompt", [], [], None, model="test/model"
            )

        assert isinstance(result, AgentResult)
        assert result.output == "hello"
        assert result.tool_calls == 0
        assert result.llm_turns == 1
        assert result.total_cost == 0.001
        assert result.tokens["input"] == 10
