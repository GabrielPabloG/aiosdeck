"""Tests for OpenCodeAdapter — permissions, subprocess interaction."""

import json
from unittest.mock import patch

from aios.agents.developer import DeveloperAgent
from aios.runtime.opencode import OpenCodeAdapter


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


def test_developer_agent_capabilities_do_not_include_question():
    assert "question" not in DeveloperAgent.required_capabilities
