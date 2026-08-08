"""Integration tests for routing in runtime and agents."""

import json
from unittest.mock import MagicMock, patch

from aios.agents.contracts import AgentTask
from aios.agents.developer import DeveloperAgent
from aios.agents.planner import PlannerAgent
from aios.config.schema import RouteConfig
from aios.routing.engine import RuleBasedRouter
from aios.runtime import RuntimeEngine


class TestOpenCodeAdapterModelArgs:
    def test_model_flag_inserted_before_auto(self):
        from aios.runtime.opencode import OpenCodeAdapter

        adapter = OpenCodeAdapter()
        adapter._resolved_command = "opencode"
        adapter._opencode_installed = True

        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "ok"
            mock_result.stderr = ""
            mock_run.return_value = mock_result

            adapter.execute("hello", [], model="anthropic/claude-sonnet")
            args = mock_run.call_args[0][0]
            auto_idx = args.index("--auto")
            model_idx = args.index("-m")
            assert model_idx < auto_idx
            assert args[model_idx + 1] == "anthropic/claude-sonnet"

    def test_variant_flag_inserted_before_auto(self):
        from aios.runtime.opencode import OpenCodeAdapter

        adapter = OpenCodeAdapter()
        adapter._resolved_command = "opencode"
        adapter._opencode_installed = True

        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "ok"
            mock_result.stderr = ""
            mock_run.return_value = mock_result

            adapter.execute("hello", [], variant="high")
            args = mock_run.call_args[0][0]
            auto_idx = args.index("--auto")
            variant_idx = args.index("--variant")
            assert variant_idx < auto_idx
            assert args[variant_idx + 1] == "high"

    def test_no_model_no_variant_legacy_args(self):
        from aios.runtime.opencode import OpenCodeAdapter

        adapter = OpenCodeAdapter()
        adapter._resolved_command = "opencode"
        adapter._opencode_installed = True

        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "ok"
            mock_result.stderr = ""
            mock_run.return_value = mock_result

            adapter.execute("hello", [])
            args = mock_run.call_args[0][0]
            assert "-m" not in args
            assert "--variant" not in args
            assert args[-1] == "--auto"

    def test_model_and_variant_both_inserted(self):
        from aios.runtime.opencode import OpenCodeAdapter

        adapter = OpenCodeAdapter()
        adapter._resolved_command = "opencode"
        adapter._opencode_installed = True

        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "ok"
            mock_result.stderr = ""
            mock_run.return_value = mock_result

            adapter.execute("hello", [], model="anthropic/claude-sonnet", variant="high")
            args = mock_run.call_args[0][0]
            model_idx = args.index("-m")
            variant_idx = args.index("--variant")
            auto_idx = args.index("--auto")
            assert model_idx < variant_idx < auto_idx
            assert args[model_idx + 1] == "anthropic/claude-sonnet"
            assert args[variant_idx + 1] == "high"


class FakeRuntimeAdapter:
    name = "fake"
    version = "1.0"

    def __init__(self):
        self.calls: list[dict] = []
        self._fail_count = 0
        self._fail_models: set[str] = set()

    def initialize(self):
        pass

    def health_check(self):
        return True

    def shutdown(self):
        pass

    @property
    def command(self):
        return "fake"

    @property
    def has_sandbox(self):
        return False

    def execute(  # noqa: PLR0913
        self, prompt, skills, capabilities=None, permissions=None, *, model="", variant=""
    ):
        self.calls.append({"model": model, "variant": variant, "prompt": prompt})
        if self._fail_count > 0:
            self._fail_count -= 1
            raise RuntimeError("simulated failure")
        if model in self._fail_models:
            self._fail_models.discard(model)
            raise RuntimeError("simulated model failure")
        return json.dumps({"ok": True, "model": model, "variant": variant})

    def fail_next(self, count: int = 1):
        self._fail_count = count

    def fail_model(self, model: str):
        self._fail_models.add(model)


class TestRuntimeEngineRoutingIntegration:
    def test_no_router_legacy_behavior(self):
        adapter = FakeRuntimeAdapter()
        engine = RuntimeEngine(adapter=adapter, router=None)
        result = engine.execute("hello", [], agent="developer")
        assert "ok" in result
        assert adapter.calls[0]["model"] == ""
        assert adapter.calls[0]["variant"] == ""

    def test_router_selects_model(self):
        adapter = FakeRuntimeAdapter()
        config = RouteConfig(
            default_provider="ollama",
            default_model="llama3",
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
        engine = RuntimeEngine(adapter=adapter, router=router)
        result = engine.execute("plan this", [], agent="planner", complexity="high")
        assert "ok" in result
        assert adapter.calls[0]["model"] == "anthropic/claude-sonnet"
        assert adapter.calls[0]["variant"] == "high"

    def test_explicit_model_override_skips_router(self):
        adapter = FakeRuntimeAdapter()
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
        )
        router = RuleBasedRouter(config)
        engine = RuntimeEngine(adapter=adapter, router=router)
        engine.execute("hello", [], agent="planner", model="ollama/mistral")
        assert adapter.calls[0]["model"] == "ollama/mistral"

    def test_fallback_chain_tried_on_failure(self):
        adapter = FakeRuntimeAdapter()
        adapter.fail_next(1)
        config = RouteConfig(
            default_provider="ollama",
            default_model="llama3",
            rules=[
                {
                    "agent": "developer",
                    "provider": "anthropic",
                    "model": "claude-sonnet",
                },
            ],
            fallback_providers=[
                {"provider": "ollama", "model": "llama3"},
            ],
        )
        router = RuleBasedRouter(config)
        engine = RuntimeEngine(adapter=adapter, router=router)
        result = engine.execute("hello", [], agent="developer")
        assert len(adapter.calls) == 2
        assert adapter.calls[0]["model"] == "anthropic/claude-sonnet"
        assert adapter.calls[1]["model"] == "ollama/llama3"
        assert "ok" in result

    def test_all_fallbacks_exhausted_raises(self):
        adapter = FakeRuntimeAdapter()
        adapter.fail_next(5)
        config = RouteConfig(
            default_provider="ollama",
            default_model="llama3",
            rules=[
                {
                    "agent": "developer",
                    "provider": "anthropic",
                    "model": "claude-sonnet",
                },
            ],
            fallback_providers=[
                {"provider": "ollama", "model": "llama3"},
            ],
        )
        router = RuleBasedRouter(config)
        engine = RuntimeEngine(adapter=adapter, router=router)
        from aios.runtime import RouteFallbackExhausted

        try:
            engine.execute("hello", [], agent="developer")
            raise AssertionError("Expected RouteFallbackExhausted")
        except RouteFallbackExhausted:
            pass

    def test_fallback_stops_on_first_success(self):
        adapter = FakeRuntimeAdapter()
        adapter.fail_model("anthropic/claude-sonnet")
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
                {"provider": "ollama", "model": "codellama"},
            ],
        )
        router = RuleBasedRouter(config)
        engine = RuntimeEngine(adapter=adapter, router=router)
        result = engine.execute("hello", [], agent="planner")
        assert len(adapter.calls) == 2
        assert adapter.calls[1]["model"] == "ollama/llama3"
        assert "ok" in result


class TestAgentRoutingIntegration:
    def test_developer_passes_agent_context(self):
        adapter = FakeRuntimeAdapter()
        engine = RuntimeEngine(adapter=adapter, router=None)
        builder = MagicMock()
        builder.build.return_value = "test prompt"
        agent = DeveloperAgent(engine, builder=builder)

        task = AgentTask(description="fix bug", task_type="code", params={"complexity": "low"})
        context = object()

        with patch.object(agent, "required_skills", []):
            agent.execute(task, context)

        assert len(adapter.calls) >= 1

    def test_planner_passes_agent_context(self):
        adapter = FakeRuntimeAdapter()
        engine = RuntimeEngine(adapter=adapter, router=None)
        agent = PlannerAgent(engine)

        task = AgentTask(
            description="plan feature", task_type="plan", params={"complexity": "high"}
        )
        context = object()

        agent._build_transcript_prompt = lambda t: "plan prompt"
        result_cls = type(
            "R",
            (),
            {
                "success": True,
                "agent": "",
                "task_id": "",
                "correlation_id": "",
                "status": "succeeded",
            },
        )
        agent._parse_plan = lambda o: result_cls()
        agent._exec_tool_call = lambda o: None
        agent._build_planning_prompt = lambda t, c, **kw: "plan prompt"

        agent.execute(task, context)
        assert len(adapter.calls) >= 1
