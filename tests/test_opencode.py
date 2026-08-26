"""Tests for OpenCodeAdapter — permissions, subprocess interaction."""

import json
from unittest.mock import patch

from aios.agents.developer import DeveloperAgent
from aios.runtime.opencode import OpenCodeAdapter
from aios.security.actions import (
    FILESYSTEM_READ_ACTION,
    FILESYSTEM_WRITE_ACTION,
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
            assert "unknown error" in str(exc)
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
