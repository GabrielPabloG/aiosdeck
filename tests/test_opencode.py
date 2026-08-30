"""Tests for OpenCodeAdapter — permissions, subprocess interaction."""

import json
import logging
import subprocess
from unittest.mock import patch

from aios.agents.developer import DeveloperAgent
from aios.runtime.opencode import OpenCodeAdapter
from aios.security.actions import (
    FILESYSTEM_READ_ACTION,
    FILESYSTEM_WRITE_ACTION,
    NETWORK_ACCESS,
    SHELL_EXECUTE,
)
from aios.security.contracts import EffectivePermissions

_DEVELOPER_CAPABILITIES = ["filesystem_read", "filesystem_write", "shell"]
_DEVELOPER_EFFECTIVE = EffectivePermissions(
    allowed=frozenset({FILESYSTEM_READ_ACTION, FILESYSTEM_WRITE_ACTION, SHELL_EXECUTE})
)


def _runnable_adapter() -> OpenCodeAdapter:
    adapter = OpenCodeAdapter()
    adapter._resolved_command = "opencode"
    adapter._opencode_installed = True
    return adapter


def _successful_run(mock_run) -> None:
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "done"
    mock_run.return_value.stderr = ""


def test_build_permissions_denies_question_even_when_in_capabilities():
    adapter = OpenCodeAdapter()
    result = adapter._build_permissions(["question", "ask_user"])
    perms = json.loads(result)
    assert perms["question"] == "deny"


def test_build_permissions_denies_question_when_not_in_capabilities():
    adapter = OpenCodeAdapter()
    result = adapter._build_permissions(["filesystem_read", "shell"])
    perms = json.loads(result)
    assert perms["question"] == "deny"


def test_execute_always_uses_capture_output_even_with_question():
    adapter = OpenCodeAdapter()

    with (
        patch("aios.runtime.opencode.shutil.which", return_value="/usr/bin/opencode"),
        patch("aios.runtime.opencode.subprocess.run") as mock_run,
    ):
        adapter.initialize()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "done"

        adapter.execute("test", skills=[], capabilities=["question"])

        mock_run.assert_called_once()
        kwargs = mock_run.call_args.kwargs
        assert kwargs.get("capture_output") is True
        assert "stdin" not in kwargs
        assert "stdout" not in kwargs


def test_execute_without_question_keeps_capture_output():
    adapter = OpenCodeAdapter()

    with (
        patch("aios.runtime.opencode.shutil.which", return_value="/usr/bin/opencode"),
        patch("aios.runtime.opencode.subprocess.run") as mock_run,
    ):
        adapter.initialize()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "done"

        adapter.execute("test", skills=[], capabilities=["filesystem_read", "shell"])

        mock_run.assert_called_once()
        kwargs = mock_run.call_args.kwargs
        assert kwargs.get("capture_output") is True


def test_execute_with_question_handles_none_stdout():
    adapter = OpenCodeAdapter()

    with (
        patch("aios.runtime.opencode.shutil.which", return_value="/usr/bin/opencode"),
        patch("aios.runtime.opencode.subprocess.run") as mock_run,
    ):
        adapter.initialize()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = None

        result = adapter.execute("test", skills=[], capabilities=["question"])

        assert result == ""


def test_execute_with_question_handles_none_stderr_on_error():
    adapter = OpenCodeAdapter()

    with (
        patch("aios.runtime.opencode.shutil.which", return_value="/usr/bin/opencode"),
        patch("aios.runtime.opencode.subprocess.run") as mock_run,
    ):
        adapter.initialize()
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = None

        try:
            adapter.execute("test", skills=[], capabilities=["question"])
        except RuntimeError as exc:
            assert str(exc) == "Runtime exited with code 1: unknown error"
        else:
            raise AssertionError("Expected RuntimeError")


def test_execute_never_passes_stdin():
    adapter = OpenCodeAdapter()

    with (
        patch("aios.runtime.opencode.shutil.which", return_value="/usr/bin/opencode"),
        patch("aios.runtime.opencode.subprocess.run") as mock_run,
    ):
        adapter.initialize()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "done"

        adapter.execute("test", skills=[], capabilities=["question"])

        mock_run.assert_called_once()
        kwargs = mock_run.call_args.kwargs
        assert "stdin" not in kwargs
        assert "stdout" not in kwargs


def test_execute_passes_ollama_model_to_opencode():
    adapter = OpenCodeAdapter()
    adapter._resolved_command = "opencode"
    adapter._opencode_installed = True

    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "done"
        mock_run.return_value.stderr = ""

        adapter.execute("test", skills=[], model="ollama/llama3.2")

    args = mock_run.call_args.args[0]
    assert args[args.index("-m") + 1] == "ollama/llama3.2"
    assert args[-1] == "--auto"


def test_developer_agent_capabilities_do_not_include_question():
    assert "question" not in DeveloperAgent.required_capabilities


def test_execute_selects_build_agent_for_write_capabilities():
    adapter = _runnable_adapter()

    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        _successful_run(mock_run)
        adapter.execute("test", skills=[], capabilities=_DEVELOPER_CAPABILITIES)

    args = mock_run.call_args.args[0]
    assert args[args.index("--agent") + 1] == "build"


def test_execute_selects_build_agent_for_effective_write_permissions():
    adapter = _runnable_adapter()

    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        _successful_run(mock_run)
        adapter.execute("test", skills=[], capabilities=[], permissions=_DEVELOPER_EFFECTIVE)

    args = mock_run.call_args.args[0]
    assert args[args.index("--agent") + 1] == "build"


def test_execute_omits_agent_flag_for_read_only_capabilities():
    adapter = _runnable_adapter()

    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        _successful_run(mock_run)
        adapter.execute("test", skills=[], capabilities=["filesystem_read"])

    args = mock_run.call_args.args[0]
    assert "--agent" not in args


def test_execute_omits_agent_flag_for_empty_effective_permissions():
    adapter = _runnable_adapter()

    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        _successful_run(mock_run)
        adapter.execute(
            "test",
            skills=[],
            capabilities=[],
            permissions=EffectivePermissions(allowed=frozenset()),
        )

    args = mock_run.call_args.args[0]
    assert "--agent" not in args


def test_execute_selects_build_agent_for_shell_only_capabilities():
    adapter = _runnable_adapter()

    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        _successful_run(mock_run)
        adapter.execute("test", skills=[], capabilities=["shell"])

    args = mock_run.call_args.args[0]
    assert args[args.index("--agent") + 1] == "build"


def test_execute_selects_build_agent_for_write_only_capabilities():
    adapter = _runnable_adapter()

    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        _successful_run(mock_run)
        adapter.execute("test", skills=[], capabilities=["filesystem_write"])

    args = mock_run.call_args.args[0]
    assert args[args.index("--agent") + 1] == "build"


def test_execute_selects_build_agent_for_effective_write_only_permissions():
    adapter = _runnable_adapter()

    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        _successful_run(mock_run)
        adapter.execute(
            "test",
            skills=[],
            capabilities=[],
            permissions=EffectivePermissions(allowed=frozenset({FILESYSTEM_WRITE_ACTION})),
        )

    args = mock_run.call_args.args[0]
    assert args[args.index("--agent") + 1] == "build"


def test_execute_selects_build_agent_for_raw_frozenset_permissions():
    adapter = _runnable_adapter()

    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        _successful_run(mock_run)
        adapter.execute(
            "test",
            skills=[],
            capabilities=[],
            permissions=frozenset({FILESYSTEM_WRITE_ACTION}),
        )

    args = mock_run.call_args.args[0]
    assert args[args.index("--agent") + 1] == "build"


def test_execute_selected_agent_does_not_weaken_permissions():
    adapter = _runnable_adapter()

    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        _successful_run(mock_run)
        adapter.execute("test", skills=[], capabilities=[], permissions=_DEVELOPER_EFFECTIVE)

    env = mock_run.call_args.kwargs["env"]
    perms = json.loads(env["OPENCODE_PERMISSION"])
    assert perms["question"] == "deny"
    assert perms["edit"] == "allow"
    bash_rules = perms["bash"]
    assert bash_rules["*"] == "deny"
    assert bash_rules["git push *"] == "deny"
    assert bash_rules["git tag *"] == "deny"
    assert bash_rules["rm -rf *"] == "deny"


# ---------------------------------------------------------------------------
# __init__ / initialize / _resolve_command / command / has_sandbox / health
# ---------------------------------------------------------------------------


def test_init_defaults():
    adapter = OpenCodeAdapter()
    assert adapter._resolved_command == "opencode"
    assert adapter._opencode_installed is False
    assert adapter._ai_jail_installed is False
    assert adapter._initialized is False
    assert adapter._permission_cache == {}
    assert adapter.name == "opencode"
    assert adapter.version == "1.0"


def test_health_check_reports_opencode_only():
    assert OpenCodeAdapter().health_check() is False
    adapter = OpenCodeAdapter()
    adapter._opencode_installed = True
    assert adapter.health_check() is True


def test_shutdown_is_noop():
    adapter = OpenCodeAdapter()
    adapter.shutdown()


def test_initialize_resolves_ai_jail_command():
    adapter = OpenCodeAdapter()
    with patch(
        "aios.runtime.opencode.shutil.which",
        side_effect=lambda name: {
            "opencode": "/usr/bin/opencode",
            "ai-jail": "/usr/bin/ai-jail",
        }[name],
    ):
        adapter.initialize()
    assert adapter._initialized is True
    assert adapter._opencode_installed is True
    assert adapter._ai_jail_installed is True
    assert adapter.command == "ai-jail opencode"
    assert adapter.has_sandbox is True


def test_initialize_without_ai_jail_degrades_command():
    adapter = OpenCodeAdapter()
    with patch(
        "aios.runtime.opencode.shutil.which",
        side_effect=lambda name: "/usr/bin/opencode" if name == "opencode" else None,
    ):
        adapter.initialize()
    assert adapter._opencode_installed is True
    assert adapter._ai_jail_installed is False
    assert adapter.command == "ai-jail opencode (not found)"
    assert adapter.has_sandbox is False
    assert adapter._resolved_command == "ai-jail opencode (not found)"


def test_initialize_without_ai_jail_logs_warning(caplog):
    adapter = OpenCodeAdapter()
    with (
        patch(
            "aios.runtime.opencode.shutil.which",
            side_effect=lambda name: "/usr/bin/opencode" if name == "opencode" else None,
        ),
        caplog.at_level(logging.WARNING, logger="aios.runtime.opencode"),
    ):
        adapter.initialize()
    assert any("ai-jail not found" in r.message for r in caplog.records)


def test_initialize_without_opencode():
    adapter = OpenCodeAdapter()
    with patch("aios.runtime.opencode.shutil.which", side_effect=lambda name: None):
        adapter.initialize()
    assert adapter._opencode_installed is False
    assert adapter.command == "opencode (not found)"
    assert adapter.health_check() is False


def test_resolve_command_without_opencode_returns_not_found():
    adapter = OpenCodeAdapter()
    adapter._opencode_installed = False
    adapter._resolve_command()
    assert adapter._resolved_command == "opencode (not found)"


# ---------------------------------------------------------------------------
# diagnose() — every RuntimeDiagnostic branch
# ---------------------------------------------------------------------------


def _set_adapter_installed(adapter, opencode=True, ai_jail=True) -> None:
    adapter._opencode_installed = opencode
    adapter._ai_jail_installed = ai_jail
    adapter._initialized = True


def test_diagnose_opencode_missing():
    adapter = OpenCodeAdapter()
    _set_adapter_installed(adapter, opencode=False, ai_jail=True)
    diag = adapter.diagnose(provider="ollama", model="ollama/llama3.2")
    assert diag.healthy is False
    assert diag.code == "opencode_missing"
    assert diag.message == "OpenCode executable was not found."
    assert diag.suggestions == ["Install OpenCode and ensure it is available on PATH."]
    assert diag.checks == {"opencode": False, "ai_jail": True}
    assert diag.source == "default"
    assert diag.provider == "ollama"
    assert diag.model == "ollama/llama3.2"
    assert diag.provider == "ollama"
    assert diag.model == "ollama/llama3.2"


def test_diagnose_ai_jail_missing():
    adapter = OpenCodeAdapter()
    _set_adapter_installed(adapter, opencode=True, ai_jail=False)
    diag = adapter.diagnose(provider="ollama", model="ollama/llama3.2")
    assert diag.healthy is False
    assert diag.code == "ai_jail_missing"
    assert diag.message == "ai-jail is required to run OpenCode safely."
    assert diag.suggestions == ["Install ai-jail; OpenCode will not run without the sandbox."]
    assert diag.checks == {"opencode": True, "ai_jail": False}
    assert diag.source == "default"
    assert diag.provider == "ollama"
    assert diag.model == "ollama/llama3.2"


def test_diagnose_provider_missing():
    adapter = OpenCodeAdapter()
    _set_adapter_installed(adapter)
    diag = adapter.diagnose(provider="", model="ollama/llama3.2")
    assert diag.healthy is False
    assert diag.code == "provider_missing"
    assert diag.message == "No provider was resolved for the runtime."
    assert diag.suggestions == ["Configure routing.default_provider."]
    assert diag.source == "default"
    assert diag.provider == ""
    assert diag.model == "ollama/llama3.2"
    assert diag.checks == {"opencode": True, "ai_jail": True}


def test_diagnose_model_missing_when_empty():
    adapter = OpenCodeAdapter()
    _set_adapter_installed(adapter)
    diag = adapter.diagnose(provider="ollama", model="")
    assert diag.healthy is False
    assert diag.code == "model_missing"
    assert diag.message == "No model was resolved for provider 'ollama'."
    assert diag.suggestions == ["Configure routing.default_model or run opencode models ollama."]
    assert diag.source == "default"
    assert diag.provider == "ollama"
    assert diag.model == ""
    assert diag.checks == {"opencode": True, "ai_jail": True}


def test_diagnose_model_missing_when_equal_to_provider():
    adapter = OpenCodeAdapter()
    _set_adapter_installed(adapter)
    diag = adapter.diagnose(provider="ollama", model="ollama")
    assert diag.healthy is False
    assert diag.code == "model_missing"
    assert diag.source == "default"
    assert diag.provider == "ollama"
    assert diag.model == "ollama"
    assert diag.checks == {"opencode": True, "ai_jail": True}


def test_diagnose_endpoint_unreachable_on_oserror():
    adapter = OpenCodeAdapter()
    _set_adapter_installed(adapter)
    with patch("aios.runtime.opencode.subprocess.run", side_effect=OSError("boom")):
        diag = adapter.diagnose(provider="ollama", model="ollama/llama3.2")
    assert diag.healthy is False
    assert diag.code == "endpoint_unreachable"
    assert diag.message == ("Could not query provider 'ollama' from inside ai-jail: boom")
    assert diag.checks["endpoint"] is False
    assert diag.suggestions == ["Check the ollama endpoint and run opencode models ollama."]
    assert diag.source == "default"
    assert diag.provider == "ollama"
    assert diag.model == "ollama/llama3.2"
    assert diag.checks == {"opencode": True, "ai_jail": True, "endpoint": False, "model": False}
    assert diag.code == "endpoint_unreachable"


def test_diagnose_endpoint_unreachable_on_timeout():
    adapter = OpenCodeAdapter()
    _set_adapter_installed(adapter)
    with patch(
        "aios.runtime.opencode.subprocess.run",
        side_effect=subprocess.TimeoutExpired("cmd", timeout=30),
    ):
        diag = adapter.diagnose(provider="ollama", model="ollama/llama3.2")
    assert diag.healthy is False
    assert diag.code == "endpoint_unreachable"


def test_diagnose_endpoint_unreachable_on_nonzero_exit():
    adapter = OpenCodeAdapter()
    _set_adapter_installed(adapter)
    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "connection refused"
        diag = adapter.diagnose(provider="ollama", model="ollama/llama3.2")
    assert diag.healthy is False
    assert diag.code == "endpoint_unreachable"
    assert diag.message == (
        "Provider 'ollama' is not reachable from inside ai-jail: connection refused"
    )
    assert diag.checks["endpoint"] is False
    assert diag.suggestions == ["Check the ollama endpoint and run opencode models ollama."]
    assert diag.source == "default"
    assert diag.provider == "ollama"
    assert diag.model == "ollama/llama3.2"
    assert diag.checks == {"opencode": True, "ai_jail": True, "endpoint": False, "model": False}


def test_diagnose_endpoint_unreachable_redacts_stderr():
    adapter = OpenCodeAdapter()
    _set_adapter_installed(adapter)
    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "boom happened\napi_key=sekret"
        diag = adapter.diagnose(provider="ollama", model="ollama/llama3.2")
    assert diag.code == "endpoint_unreachable"
    assert "boom happened" in diag.message
    assert "api_key=sekret" not in diag.message


def test_diagnose_model_unavailable():
    adapter = OpenCodeAdapter()
    _set_adapter_installed(adapter)
    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "some other model"
        mock_run.return_value.stderr = ""
        diag = adapter.diagnose(provider="ollama", model="ollama/llama3.2")
    assert diag.healthy is False
    assert diag.code == "model_unavailable"
    assert diag.message == "Model 'ollama/llama3.2' was not reported by provider 'ollama'."
    assert diag.checks["endpoint"] is False
    assert diag.checks["model"] is False
    assert diag.suggestions == ["Run opencode models ollama and configure an available model."]
    assert diag.source == "default"
    assert diag.provider == "ollama"
    assert diag.model == "ollama/llama3.2"
    assert diag.checks == {"opencode": True, "ai_jail": True, "endpoint": False, "model": False}


def test_diagnose_ok():
    adapter = OpenCodeAdapter()
    _set_adapter_installed(adapter)
    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "models available: llama3.2"
        mock_run.return_value.stderr = ""
        diag = adapter.diagnose(provider="ollama", model="ollama/llama3.2")
    assert diag.healthy is True
    assert diag.code == "ok"
    assert diag.message == "OpenCode provider 'ollama' and model 'ollama/llama3.2' are available."
    assert diag.checks["endpoint"] is True
    assert diag.checks["model"] is True
    assert diag.source == "default"
    assert diag.provider == "ollama"
    assert diag.model == "ollama/llama3.2"
    assert diag.checks == {"opencode": True, "ai_jail": True, "endpoint": True, "model": True}
    assert diag.suggestions == []


def test_diagnose_uses_ai_jail_command():
    adapter = OpenCodeAdapter()
    _set_adapter_installed(adapter)
    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "llama3.2"
        mock_run.return_value.stderr = ""
        adapter.diagnose(provider="ollama", model="ollama/llama3.2")
    args = mock_run.call_args.args[0]
    assert args[:2] == ["ai-jail", "opencode"]
    assert args[2:] == ["models", "ollama"]
    kwargs = mock_run.call_args.kwargs
    assert kwargs["timeout"] == 30
    assert kwargs["text"] is True
    assert kwargs["capture_output"] is True
    assert kwargs["check"] is False


# ---------------------------------------------------------------------------
# execute() — argument assembly, env, and error branches
# ---------------------------------------------------------------------------


def test_execute_runs_provider_model_variant_and_auto():
    adapter = _runnable_adapter()
    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        _successful_run(mock_run)
        adapter.execute(
            "hello",
            skills=[],
            model="ollama/llama3.2",
            variant="high",
        )
    args = mock_run.call_args.args[0]
    assert args == [
        "opencode",
        "run",
        "hello",
        "-m",
        "ollama/llama3.2",
        "--variant",
        "high",
        "--auto",
    ]


def test_execute_injects_permission_env():
    adapter = _runnable_adapter()
    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        _successful_run(mock_run)
        adapter.execute("test", skills=[], capabilities=["filesystem_read"])
    env = mock_run.call_args.kwargs["env"]
    assert "OPENCODE_PERMISSION" in env
    assert json.loads(env["OPENCODE_PERMISSION"])["question"] == "deny"
    assert mock_run.call_args.kwargs["timeout"] == 600
    assert mock_run.call_args.kwargs["text"] is True
    assert mock_run.call_args.kwargs["capture_output"] is True
    assert mock_run.call_args.kwargs["check"] is False


def test_execute_raises_when_opencode_not_installed():
    adapter = OpenCodeAdapter()
    adapter._opencode_installed = False
    try:
        adapter.execute("test", skills=[], capabilities=[])
    except RuntimeError as exc:
        assert "Runtime not available" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError")


def test_execute_raises_when_ai_jail_missing():
    adapter = OpenCodeAdapter()
    adapter._opencode_installed = True
    adapter._ai_jail_installed = False
    adapter._initialized = True
    adapter._resolved_command = "ai-jail opencode (not found)"
    try:
        adapter.execute("test", skills=[], capabilities=[])
    except RuntimeError as exc:
        assert str(exc) == "Runtime requires ai-jail (sandbox is mandatory)"
    else:
        raise AssertionError("Expected RuntimeError")


def test_execute_raises_on_timeout():
    adapter = _runnable_adapter()
    with patch(
        "aios.runtime.opencode.subprocess.run",
        side_effect=subprocess.TimeoutExpired("opencode run test", timeout=600),
    ):
        try:
            adapter.execute("test", skills=[], capabilities=[])
        except RuntimeError as exc:
            assert str(exc) == "Runtime execution timed out after 600s"
        else:
            raise AssertionError("Expected RuntimeError")


def test_execute_raises_on_file_not_found():
    adapter = _runnable_adapter()
    with patch("aios.runtime.opencode.subprocess.run", side_effect=FileNotFoundError):
        try:
            adapter.execute("test", skills=[], capabilities=[])
        except RuntimeError as exc:
            assert "command not found" in str(exc)
        else:
            raise AssertionError("Expected RuntimeError")


def test_execute_raises_on_nonzero_exit_with_redacted_stderr():
    adapter = _runnable_adapter()
    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "boom happened\napi_key=sekret"
        try:
            adapter.execute("test", skills=[], capabilities=[])
        except RuntimeError as exc:
            assert "boom happened" in str(exc)
            assert "api_key=sekret" not in str(exc)
        else:
            raise AssertionError("Expected RuntimeError")


def test_execute_returns_stdout_stripped():
    adapter = _runnable_adapter()
    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "  done output  "
        mock_run.return_value.stderr = ""
        result = adapter.execute("test", skills=[], capabilities=[])
    assert result == "done output"


# ---------------------------------------------------------------------------
# _redact_detail()
# ---------------------------------------------------------------------------


def test_redact_detail_filters_secret_lines():
    detail = (
        "everything ok\ntoken=abc\napi_key=zzz\napikey=k\npassword=pw\n"
        "secret=s\nauthorization: Bearer xyz\n"
    )
    result = OpenCodeAdapter._redact_detail(detail)
    assert result == "everything ok"


def test_redact_detail_keeps_non_secret_multiline():
    detail = "first line\nsecond line"
    result = OpenCodeAdapter._redact_detail(detail)
    assert result == "first line\nsecond line"


def test_redact_detail_fallback_on_empty():
    assert OpenCodeAdapter._redact_detail("") == "provider returned an error"
    assert OpenCodeAdapter._redact_detail("   \n  ") == "provider returned an error"


def test_redact_detail_returns_provider_error_when_all_filtered():
    assert OpenCodeAdapter._redact_detail("token=secret\n") == "provider returned an error"


# ---------------------------------------------------------------------------
# _build_permissions() branching (permissions object vs frozenset vs list)
# ---------------------------------------------------------------------------


def test_build_permissions_with_effective_object():
    adapter = OpenCodeAdapter()
    result = adapter._build_permissions(_DEVELOPER_EFFECTIVE)
    perms = json.loads(result)
    assert perms["edit"] == "allow"


def test_build_permissions_with_frozenset():
    adapter = OpenCodeAdapter()
    result = adapter._build_permissions(frozenset({FILESYSTEM_READ_ACTION}))
    perms = json.loads(result)
    assert perms["read"] == "allow"
    assert perms["edit"] == "deny"


# ---------------------------------------------------------------------------
# _build_legacy_permissions() matrix
# ---------------------------------------------------------------------------


def test_build_legacy_permissions_locks_edit_and_bash_without_write_or_shell():
    adapter = OpenCodeAdapter()
    result = adapter._build_legacy_permissions(["filesystem_read"])
    perms = json.loads(result)
    assert perms["edit"] == "deny"
    assert perms["bash"] == "deny"


def test_build_legacy_permissions_allows_with_write():
    adapter = OpenCodeAdapter()
    result = adapter._build_legacy_permissions(["filesystem_read", "filesystem_write"])
    perms = json.loads(result)
    assert "edit" not in perms
    assert "bash" not in perms


def test_build_legacy_permissions_allows_with_shell():
    adapter = OpenCodeAdapter()
    result = adapter._build_legacy_permissions(["filesystem_read", "shell"])
    perms = json.loads(result)
    assert "bash" not in perms


def test_build_legacy_permissions_cache_key():
    adapter = OpenCodeAdapter()
    first = adapter._build_legacy_permissions(["filesystem_read"])
    second = adapter._build_legacy_permissions(["filesystem_read"])
    assert first == second
    assert any(k[0] == "legacy" for k in adapter._permission_cache)


# ---------------------------------------------------------------------------
# _build_effective_permissions() matrix
# ---------------------------------------------------------------------------

_BASH_RULES_EXPECTED = {
    "*": "deny",
    "git push *": "deny",
    "git tag *": "deny",
    "rm -rf *": "deny",
    "curl *": "deny",
    "wget *": "deny",
    "git branch *": "allow",
    "git commit *": "allow",
    "grep *": "allow",
    "ruff *": "allow",
    "python *": "allow",
    "pytest *": "allow",
}


def _build_effective(adapter, *actions):
    return json.loads(
        adapter._build_effective_permissions(EffectivePermissions(allowed=frozenset(actions)))
    )


def test_build_effective_permissions_read_only():
    perms = _build_effective(OpenCodeAdapter(), FILESYSTEM_READ_ACTION)
    assert perms["read"] == "allow"
    assert perms["glob"] == "allow"
    assert perms["grep"] == "allow"
    assert perms["edit"] == "deny"
    assert perms["bash"] == "deny"
    assert perms["webfetch"] == "deny"
    assert perms["websearch"] == "deny"
    assert perms["question"] == "deny"


def test_build_effective_permissions_write():
    perms = _build_effective(OpenCodeAdapter(), FILESYSTEM_WRITE_ACTION)
    assert perms["edit"] == "allow"
    assert perms["read"] == "deny"
    assert perms["bash"] == "deny"


def test_build_effective_permissions_network():
    perms = _build_effective(OpenCodeAdapter(), NETWORK_ACCESS)
    assert perms["webfetch"] == "allow"
    assert perms["websearch"] == "allow"
    assert perms["edit"] == "deny"


def test_build_effective_permissions_shell_full_rules():
    perms = _build_effective(OpenCodeAdapter(), SHELL_EXECUTE)
    assert perms["bash"] == _BASH_RULES_EXPECTED


def test_build_effective_permissions_combined_and_cache():
    adapter = OpenCodeAdapter()
    perms = adapter._build_effective_permissions(_DEVELOPER_EFFECTIVE)
    env_json = perms
    parsed = json.loads(env_json)
    assert parsed["read"] == "allow"
    assert parsed["edit"] == "allow"
    assert parsed["bash"] == _BASH_RULES_EXPECTED
    assert any(k[0] == "effective" for k in adapter._permission_cache)


# ---------------------------------------------------------------------------
# Additional targeted tests to kill specific mutants
# ---------------------------------------------------------------------------


def test_initialize_without_ai_jail_logs_exact_warning(caplog):
    adapter = OpenCodeAdapter()
    with (
        patch(
            "aios.runtime.opencode.shutil.which",
            side_effect=lambda name: "/usr/bin/opencode" if name == "opencode" else None,
        ),
        caplog.at_level(logging.WARNING, logger="aios.runtime.opencode"),
    ):
        adapter.initialize()
    assert len(caplog.records) == 1
    assert caplog.records[0].message == "ai-jail not found. OpenCode execution is disabled."


def test_build_permissions_frozenset_branch():
    adapter = OpenCodeAdapter()
    result = adapter._build_permissions(frozenset({FILESYSTEM_READ_ACTION}))
    perms = json.loads(result)
    assert perms["read"] == "allow"
    assert perms["glob"] == "allow"
    assert perms["grep"] == "allow"
    assert perms["edit"] == "deny"
    assert perms["bash"] == "deny"
    assert perms["webfetch"] == "deny"
    assert perms["websearch"] == "deny"
    assert perms["question"] == "deny"


def test_build_permissions_capabilities_fallback_or():
    # _build_permissions with None and capabilities list uses `capabilities or []`
    adapter = OpenCodeAdapter()
    # effective=None, capabilities provided -> legacy path with capabilities
    result = adapter._build_permissions(None, capabilities=["filesystem_read"])
    perms = json.loads(result)
    # legacy path: has write -> edit allowed (but filesystem_read has no write/shell)
    assert perms["edit"] == "deny"
    assert perms["bash"] == "deny"


def test_build_legacy_permissions_capabilities_and():
    # _build_permissions with None and capabilities uses `capabilities or []`
    # The mutant is in _build_permissions line: `capabilities or []` -> `capabilities and []`
    # This test verifies the `or []` behavior with non-empty capabilities
    adapter = OpenCodeAdapter()
    # effective=None, capabilities provided -> legacy path with those capabilities
    result = adapter._build_permissions(None, capabilities=["filesystem_read"])
    perms = json.loads(result)
    assert perms["edit"] == "deny"
    assert perms["bash"] == "deny"


def test_build_effective_permissions_deny_branch():
    # read=False -> glob/grep deny (covers mutmut 32,33,38,39)
    perms = _build_effective(OpenCodeAdapter(), FILESYSTEM_WRITE_ACTION)
    assert perms["glob"] == "deny"
    assert perms["grep"] == "deny"


def test_build_effective_permissions_cache_stores_value():
    adapter = OpenCodeAdapter()
    env_json = adapter._build_effective_permissions(_DEVELOPER_EFFECTIVE)
    # Find the effective cache key
    eff_keys = [k for k in adapter._permission_cache if k[0] == "effective"]
    assert len(eff_keys) == 1
    key = eff_keys[0]
    # Cache must store the JSON string, not None
    assert adapter._permission_cache[key] == env_json
    assert adapter._permission_cache[key] is not None


def test_build_effective_permissions_read_false_deny_glob_grep():
    # Explicit deny-branch: read=False should have glob/grep denied
    perms = _build_effective(OpenCodeAdapter(), FILESYSTEM_WRITE_ACTION)
    assert perms["glob"] == "deny"
    assert perms["grep"] == "deny"


# ---------------------------------------------------------------------------
# Mutation-gate hardening: capabilities `or []` vs `and []` / None
# (kills execute__mutmut_36/37 and _build_permissions__mutmut_5)
# ---------------------------------------------------------------------------


def test_execute_permissions_reflect_non_empty_capabilities():
    adapter = _runnable_adapter()
    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        _successful_run(mock_run)
        adapter.execute("test", skills=[], capabilities=["filesystem_write"])
    perms = json.loads(mock_run.call_args.kwargs["env"]["OPENCODE_PERMISSION"])
    assert "edit" not in perms
    assert "bash" not in perms


def test_build_permissions_capabilities_write_allows_edit():
    perms = json.loads(
        OpenCodeAdapter()._build_permissions(None, capabilities=["filesystem_write"])
    )
    assert "edit" not in perms
    assert "bash" not in perms


# ---------------------------------------------------------------------------
# Mutation-gate hardening: diagnose() runtime and literal branches
# ---------------------------------------------------------------------------


def test_diagnose_endpoint_unreachable_unknown_error_literal():
    adapter = OpenCodeAdapter()
    _set_adapter_installed(adapter)
    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = ""
        diag = adapter.diagnose(provider="ollama", model="ollama/llama3.2")
    assert diag.code == "endpoint_unreachable"
    assert diag.message == ("Provider 'ollama' is not reachable from inside ai-jail: unknown error")


def test_diagnose_ok_when_model_in_stderr_only():
    adapter = OpenCodeAdapter()
    _set_adapter_installed(adapter)
    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "llama3.2\n"
        diag = adapter.diagnose(provider="ollama", model="ollama/llama3.2")
    assert diag.code == "ok"


def test_diagnose_model_unavailable_with_double_slash_model():
    adapter = OpenCodeAdapter()
    _set_adapter_installed(adapter)
    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "b"
        mock_run.return_value.stderr = ""
        diag = adapter.diagnose(provider="ollama", model="ollama/a/b")
    assert diag.code == "model_unavailable"


def test_diagnose_ok_with_no_slash_model():
    adapter = OpenCodeAdapter()
    _set_adapter_installed(adapter)
    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "llama3.2"
        mock_run.return_value.stderr = ""
        diag = adapter.diagnose(provider="ollama", model="llama3.2")
    assert diag.code == "ok"


def test_diagnose_model_missing_strips_trailing_slash():
    adapter = OpenCodeAdapter()
    _set_adapter_installed(adapter)
    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = ""
        diag = adapter.diagnose(provider="ollama", model="ollama/")
    assert diag.code == "model_missing"


def test_diagnose_model_leading_slash_uses_rstrip():
    adapter = OpenCodeAdapter()
    _set_adapter_installed(adapter)
    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "openai"
        mock_run.return_value.stderr = ""
        diag = adapter.diagnose(provider="openai", model="/openai")
    assert diag.code == "ok"


def test_diagnose_model_rstrip_uses_slash_only():
    adapter = OpenCodeAdapter()
    _set_adapter_installed(adapter)
    with patch("aios.runtime.opencode.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "openaiX"
        mock_run.return_value.stderr = ""
        diag = adapter.diagnose(provider="openai", model="openaiX")
    assert diag.code == "ok"
