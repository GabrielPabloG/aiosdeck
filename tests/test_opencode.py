"""Tests for OpenCodeAdapter — permissions, subprocess interaction."""

import json
from unittest.mock import patch

from aios.agents.developer import DeveloperAgent
from aios.runtime.opencode import OpenCodeAdapter


def test_build_permissions_allows_question_when_in_capabilities():
    adapter = OpenCodeAdapter()
    result = adapter._build_permissions(["question"])
    perms = json.loads(result)
    assert perms["question"] == "allow"


def test_build_permissions_denies_question_when_not_in_capabilities():
    adapter = OpenCodeAdapter()
    result = adapter._build_permissions(["filesystem_read", "shell"])
    perms = json.loads(result)
    assert perms["question"] == "deny"


def test_execute_with_question_disables_capture_output():
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
        assert kwargs.get("capture_output") is False or kwargs.get("capture_output") is None


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


def test_execute_with_question_passes_stdin():
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
        assert "stdin" in kwargs


def test_developer_agent_capabilities_include_question():
    assert "question" in DeveloperAgent.required_capabilities
