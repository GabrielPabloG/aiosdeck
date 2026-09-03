"""Parity tests: route explain, real execution and doctor must agree.

Regression guarded: a project whose ``.aios/project.yaml`` configures
``routing.default_provider: opencode-go`` must never resolve to the built-in
``ollama/llama3`` defaults — neither in ``RuntimeEngine.execute`` (what the
agents actually send to the adapter) nor in ``ad doctor`` diagnostics.
Every scenario asserts against the model captured at the adapter boundary,
which is the strongest available proof of the effective decision.
"""

from pathlib import Path

import pytest

from aios.core.factory import create_kernel
from aios.routing.engine import RuleBasedRouter
from aios.routing.models import RouteInput
from aios.runtime.diagnostics import RuntimeDiagnostic

MANIFEST = """\
name: test-aiosdeck-flapy
runtime: opencode
sandbox: ai-jail

routing:
  enabled: true
  default_provider: "opencode-go"
  default_model: "opencode-go/qwen3.8-flash"

  rules:
    - agent: "planner"
      provider: "opencode-go"
      model: "opencode-go/qwen3.8-flash"
      complexity: "high"

    - agent: "developer"
      provider: "opencode-go"
      model: "opencode-go/qwen3.8-flash"
      complexity: "low"

    - agent: "reviewer"
      provider: "opencode-go"
      model: "opencode-go/qwen3.8-flash"
      complexity: "medium"

  fallback_providers:
    - provider: "google"
      model: "gemini-3.7-flash"

    - provider: "ollama"
      model: "qwen-opencode"

skills:
  - project-dna
  - coding-style
"""

EFFECTIVE_MODEL = "opencode-go/qwen3.8-flash"


@pytest.fixture
def kernel(tmp_path, monkeypatch):
    for key in (
        "AIOS_ROUTING_ENABLED",
        "AIOS_ROUTING_COST_CAP",
        "AIOS_OLLAMA_MODEL",
        "AIOS_DEFAULT_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".aios").mkdir()
    (tmp_path / ".aios" / "project.yaml").write_text(MANIFEST)
    return create_kernel(tmp_path)


def _capture_adapter(kernel):
    calls: list[dict] = []

    def fake_execute(  # noqa: PLR0913 - mirrors the adapter.execute contract
        prompt, skills, capabilities=None, permissions=None, *, model="", variant=""
    ):
        calls.append({"model": model, "variant": variant})
        return "ok"

    kernel.get_engine("runtime").adapter.execute = fake_execute
    return calls


class TestExecutionParity:
    @pytest.mark.parametrize(
        ("agent", "complexity"),
        [
            ("planner", "high"),
            ("developer", "low"),
            ("reviewer", "medium"),
            ("", "medium"),
            ("unknown-agent", "high"),
        ],
    )
    def test_adapter_receives_configured_model_never_ollama_llama3(self, kernel, agent, complexity):
        calls = _capture_adapter(kernel)

        kernel.get_engine("runtime").execute(
            "p", [], agent=agent, complexity=complexity, task_type="code"
        )

        assert calls[0]["model"] == EFFECTIVE_MODEL
        assert calls[0]["model"] != "ollama/llama3"

    def test_executed_model_matches_route_explain_decision(self, kernel):
        calls = _capture_adapter(kernel)
        from aios.config.loader import ConfigLoader

        router = RuleBasedRouter(ConfigLoader(project_path=kernel.project_path).load().routing)
        expected = router.route(RouteInput(agent="planner", complexity="high"))

        kernel.get_engine("runtime").execute(
            "p", [], agent="planner", task_type="plan", complexity="high"
        )

        assert calls[0]["model"] == expected.model
        assert calls[0]["model"] == EFFECTIVE_MODEL

    def test_fallback_chain_uses_configured_providers(self, kernel):
        calls: list[dict] = []

        def failing_first(  # noqa: PLR0913 - mirrors the adapter.execute contract
            prompt, skills, capabilities=None, permissions=None, *, model="", variant=""
        ):
            calls.append({"model": model})
            if len(calls) == 1:
                raise RuntimeError("primary endpoint down")
            return "ok"

        kernel.get_engine("runtime").adapter.execute = failing_first

        kernel.get_engine("runtime").execute("p", [], agent="planner", complexity="high")

        assert calls[0]["model"] == EFFECTIVE_MODEL
        assert calls[1]["model"] == "google/gemini-3.7-flash"


class TestDoctorReflectsRouting:
    def test_doctor_reports_effective_routing_not_legacy_default(self, kernel, tmp_path):
        captured: dict = {}

        def fake_diagnose(*, provider, model, source="default"):
            captured["provider"] = provider
            captured["model"] = model
            captured["source"] = source
            return RuntimeDiagnostic(True, "ok", "fine", source, provider, model)

        runtime = kernel.get_engine("runtime")
        runtime.adapter.diagnose = fake_diagnose

        runtime.diagnose()

        assert captured["provider"] == "opencode-go"
        assert captured["model"] == EFFECTIVE_MODEL
        assert captured["source"] == str(tmp_path / ".aios" / "project.yaml")
        assert captured["model"] != "ollama/llama3"
