"""Contract tests for RuntimeEngine.execute, route events, and diagnostics."""

import logging
from types import SimpleNamespace

import pytest

from aios.routing.models import RouteDecision
from aios.runtime import RouteFallbackExhausted, RuntimeEngine


class _Bus:
    def __init__(self):
        self.events = []

    def publish(self, topic, payload):
        self.events.append((topic, payload))


class _BoomBus:
    def publish(self, topic, payload):
        raise ValueError("bus down")


class _Router:
    def __init__(self, decision):
        self.decision = decision
        self.inputs = []

    def route(self, route_input):
        self.inputs.append(route_input)
        return self.decision


class _Adapter:
    def __init__(self, outputs=None, error=None, fail_times=None):
        self.calls = []
        self._outputs = list(outputs or [])
        self._error = error
        self._fail_times = fail_times

    def execute(  # noqa: PLR0913
        self, prompt, skills, capabilities, permissions, *, model="", variant=""
    ):
        self.calls.append(
            {
                "prompt": prompt,
                "skills": skills,
                "capabilities": capabilities,
                "permissions": permissions,
                "model": model,
                "variant": variant,
            }
        )
        should_fail = self._error is not None and (
            self._fail_times is None or len(self.calls) <= self._fail_times
        )
        if should_fail:
            raise self._error
        return self._outputs.pop(0) if self._outputs else "ok"


def _engine(adapter=None, **kwargs):
    return RuntimeEngine(adapter=adapter or _Adapter(), **kwargs)


def test_execute_legacy_defaults_forwarded_and_emitted():
    adapter = _Adapter(["ok"])
    bus = _Bus()
    engine = _engine(adapter, bus=bus)

    result = engine.execute("prompt", ["skill"], ["fs"], "perms")

    assert result == "ok"
    assert adapter.calls == [
        {
            "prompt": "prompt",
            "skills": ["skill"],
            "capabilities": ["fs"],
            "permissions": "perms",
            "model": "",
            "variant": "",
        }
    ]
    topic, payload = bus.events[0]
    assert topic == "runtime.route_selected"
    assert payload == {
        "agent": "",
        "task_type": "",
        "complexity": "medium",
        "provider": "",
        "model": "",
        "variant": "",
        "reason": "",
        "context_size": 0,
        "source": "legacy",
        "fallback_used": False,
        "fallback_reason": "",
    }


def test_execute_model_override_uses_explicit_source():
    adapter = _Adapter()
    bus = _Bus()
    engine = _engine(adapter, bus=bus)

    engine.execute("p", [], model="custom/model")

    assert adapter.calls[0]["model"] == "custom/model"
    payload = bus.events[0][1]
    assert payload["source"] == "override"
    assert payload["reason"] == "explicit_override"
    assert payload["model"] == "custom/model"


def test_execute_router_decision_forwards_and_captures_input():
    decision = RouteDecision(
        provider="prov",
        model="prov/m1",
        variant="vx",
        reason="policy:0",
        source="router",
        fallback_chain=[],
    )
    router = _Router(decision)
    adapter = _Adapter()
    bus = _Bus()
    engine = _engine(adapter, router=router, bus=bus)

    engine.execute("p", ["s"], agent="dev", complexity="", context_size=7)

    captured = router.inputs[0]
    assert captured.agent == "dev"
    assert captured.task_type == "code"
    assert captured.complexity == "medium"
    assert captured.context_size == 7

    assert adapter.calls[0]["model"] == "prov/m1"
    assert adapter.calls[0]["variant"] == "vx"

    payload = bus.events[0][1]
    assert payload["provider"] == "prov"
    assert payload["model"] == "prov/m1"
    assert payload["variant"] == "vx"
    assert payload["reason"] == "policy:0"
    assert payload["source"] == "router"
    assert payload["context_size"] == 7
    assert payload["fallback_used"] is False
    assert payload["fallback_reason"] == ""
    assert payload["agent"] == "dev"


def test_execute_sparse_fallback_attempt_uses_empty_defaults():
    adapter = _Adapter(error=TimeoutError("t"), fail_times=1)
    bus = _Bus()
    decision = RouteDecision(
        provider="prov",
        model="prov/m1",
        variant="vx",
        reason="policy:0",
        source="router",
        fallback_chain=[{"model": "solo"}],
    )
    engine = _engine(adapter, router=_Router(decision), bus=bus)

    result = engine.execute("p", [])

    assert result == "ok"
    assert adapter.calls[1]["model"] == "solo"
    assert adapter.calls[1]["variant"] == ""

    payload = bus.events[0][1]
    assert payload["provider"] == ""
    assert payload["model"] == "solo"
    assert payload["variant"] == ""
    assert payload["reason"] == ""
    assert payload["source"] == "router"
    assert payload["fallback_used"] is True
    assert payload["fallback_reason"] == "timeout"


def test_execute_raises_exhaustion_with_agent_and_last_error():
    adapter = _Adapter(error=RuntimeError("boom"))
    engine = _engine(adapter)

    with pytest.raises(RouteFallbackExhausted) as excinfo:
        engine.execute("p", [], agent="ops")

    message = str(excinfo.value)
    assert "All models exhausted for agent 'ops'" in message
    assert "Last error: boom" in message


def test_execute_logs_warning_per_failed_model(caplog):
    adapter = _Adapter(error=RuntimeError("boom"))
    engine = _engine(adapter)

    with (
        caplog.at_level(logging.WARNING, logger="aios.runtime"),
        pytest.raises(RouteFallbackExhausted),
    ):
        engine.execute("p", [])

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings[-1].getMessage() == "Model  failed: boom — trying next fallback"


def test_route_event_publish_errors_are_swallowed_and_logged(caplog):
    adapter = _Adapter()
    engine = _engine(adapter, bus=_BoomBus())

    with caplog.at_level(logging.DEBUG, logger="aios.runtime"):
        result = engine.execute("p", [], model="m")

    assert result == "ok"
    debugs = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert debugs[-1].getMessage() == "Failed to emit route event: bus down"


class TestDiagnose:
    def _adapter_recording(self):
        seen = {}
        adapter = SimpleNamespace(
            diagnose=lambda **kwargs: (seen.update(kwargs), "diag")[1]
        )
        return adapter, seen

    def test_returns_none_without_adapter_support(self):
        engine = _engine(adapter=object())
        assert engine.diagnose() is None

    def test_default_provider_model_and_source_pass_through(self):
        adapter, seen = self._adapter_recording()
        engine = _engine(adapter)
        assert engine.diagnose() == "diag"
        assert seen == {"provider": "", "model": "", "source": "default"}

    def test_router_path_uses_decision_and_config_sources(self):
        adapter, seen = self._adapter_recording()
        decision = RouteDecision(provider="rp", model="rp/m", source="router")
        router = _Router(decision)
        config = SimpleNamespace(_sources={"routing.default_model": "user.yaml"})
        engine = _engine(adapter, router=router, config=config)

        assert engine.diagnose() == "diag"

        assert router.inputs[0].agent == ""
        assert seen == {"provider": "rp", "model": "rp/m", "source": "user.yaml"}

    def test_router_path_without_sources_attr_falls_back_to_default(self):
        adapter, seen = self._adapter_recording()
        decision = RouteDecision(provider="rp", model="rp/m")
        engine = _engine(adapter, router=_Router(decision), config=SimpleNamespace())

        engine.diagnose()

        assert seen["source"] == "default"

    def test_config_only_path_resolves_model_settings(self):
        adapter, seen = self._adapter_recording()
        config = SimpleNamespace(
            model=SimpleNamespace(default="ollama", ollama_model="llama3"),
            _sources={"model.default": "env:X"},
        )
        engine = _engine(adapter, config=config)

        engine.diagnose()

        assert seen == {"provider": "ollama", "model": "ollama/llama3", "source": "env:X"}

    def test_partial_model_configs_use_empty_defaults(self):
        adapter, seen = self._adapter_recording()
        engine = _engine(adapter, config=SimpleNamespace(model=SimpleNamespace()))
        engine.diagnose()
        assert seen == {"provider": "", "model": "/", "source": "default"}

        adapter2, seen2 = self._adapter_recording()
        engine2 = _engine(
            adapter2, config=SimpleNamespace(model=SimpleNamespace(ollama_model="lm"))
        )
        engine2.diagnose()
        assert seen2 == {"provider": "", "model": "/lm", "source": "default"}

    def test_config_without_model_section_keeps_defaults(self):
        adapter, seen = self._adapter_recording()
        engine = _engine(adapter, config=SimpleNamespace())
        engine.diagnose()
        assert seen == {"provider": "", "model": "", "source": "default"}
