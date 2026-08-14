"""Contract tests for the explicit OpenCode preflight."""

from types import SimpleNamespace
from unittest.mock import patch

from aios.cli.commands.core import cmd_doctor
from aios.config.schema import AiosDeckConfig
from aios.runtime import RuntimeEngine
from aios.runtime.opencode import OpenCodeAdapter


def _adapter(*, opencode=True, ai_jail=True):
    adapter = OpenCodeAdapter()
    adapter._opencode_installed = opencode
    adapter._ai_jail_installed = ai_jail
    return adapter


def test_preflight_reports_provider_missing():
    result = _adapter().diagnose(provider="", model="", source="manifest.yaml")

    assert result.code == "provider_missing"
    assert result.source == "manifest.yaml"


def test_preflight_reports_model_missing():
    result = _adapter().diagnose(provider="ollama", model="ollama", source="env:AIOS_DEFAULT_MODEL")

    assert result.code == "model_missing"
    assert result.provider == "ollama"


def test_preflight_reports_opencode_missing():
    result = _adapter(opencode=False).diagnose(provider="ollama", model="ollama/llama3")

    assert result.code == "opencode_missing"
    assert result.checks["ai_jail"] is True


def test_preflight_reports_ai_jail_missing():
    result = _adapter(ai_jail=False).diagnose(provider="ollama", model="ollama/llama3")

    assert result.code == "ai_jail_missing"
    assert result.healthy is False


def test_preflight_distinguishes_endpoint_unreachable():
    completed = SimpleNamespace(returncode=1, stdout="", stderr="connection refused")
    with patch("aios.runtime.opencode.subprocess.run", return_value=completed) as run:
        result = _adapter().diagnose(provider="ollama", model="ollama/llama3")

    assert result.code == "endpoint_unreachable"
    assert run.call_args.args[0] == ["ai-jail", "opencode", "models", "ollama"]


def test_preflight_succeeds_for_resolved_model():
    completed = SimpleNamespace(returncode=0, stdout="ollama/llama3\n", stderr="")
    with patch("aios.runtime.opencode.subprocess.run", return_value=completed):
        result = _adapter().diagnose(provider="ollama", model="ollama/llama3")

    assert result.code == "ok"
    assert result.to_dict()["status"] == "healthy"


def test_runtime_error_keeps_actionable_stderr_without_secret_fields():
    adapter = _adapter()
    completed = SimpleNamespace(
        returncode=1,
        stdout="",
        stderr="connection refused\napi_key=do-not-print",
    )
    with patch("aios.runtime.opencode.subprocess.run", return_value=completed):
        try:
            adapter.execute("test", [], model="ollama/llama3")
        except RuntimeError as exc:
            message = str(exc)
        else:
            raise AssertionError("Expected RuntimeError")

    assert "connection refused" in message
    assert "do-not-print" not in message


def test_runtime_diagnose_uses_router_and_configuration_source():
    config = AiosDeckConfig()
    config._sources = {"routing.default_model": "/project/.aios/project.yaml"}
    runtime = RuntimeEngine(adapter=_adapter(), config=config)
    runtime._router = SimpleNamespace(
        route=lambda _input: SimpleNamespace(provider="ollama", model="ollama/llama3")
    )
    completed = SimpleNamespace(returncode=0, stdout="llama3\n", stderr="")
    with patch("aios.runtime.opencode.subprocess.run", return_value=completed):
        result = runtime.diagnose()

    assert result.source == "/project/.aios/project.yaml"
    assert result.model == "ollama/llama3"


def test_doctor_json_includes_runtime_diagnostics(capsys, tmp_path):
    diagnostic = {
        "healthy": False,
        "status": "unhealthy",
        "code": "model_missing",
        "message": "No model",
        "source": "default",
        "provider": "ollama",
        "model": "ollama",
        "checks": {},
        "suggestions": ["Run opencode models ollama."],
    }

    class FakeKernel:
        def start(self):
            pass

        def diagnose_runtime(self):
            pass

        def status(self):
            return {
                "project": str(tmp_path),
                "engines": {},
                "errors": [],
                "runtime_diagnostics": diagnostic,
            }

        def get_context(self):
            return None

    cmd_doctor(["--json"], tmp_path, lambda _path: FakeKernel())

    assert '"runtime_diagnostics"' in capsys.readouterr().out
