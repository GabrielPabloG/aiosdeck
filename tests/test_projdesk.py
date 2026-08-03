"""Tests for ProjDeskClient integration."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from aios.integrations.projdesk import (
    ProjDeskClient,
    ProjDeskError,
    ProjectAmbiguous,
    ProjectNotFound,
)


def test_resolve_success(tmp_path):
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = str(project_dir) + "\n"

        client = ProjDeskClient()
        result = client.resolve("my-project")

    assert isinstance(result, Path)
    assert result == project_dir


def test_resolve_not_a_directory(tmp_path):
    nonexistent = tmp_path / "nonexistent"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = str(nonexistent) + "\n"

        client = ProjDeskClient()
        with pytest.raises(ProjDeskError, match="not a directory"):
            client.resolve("nonexistent")


def test_resolve_project_not_found():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1

        client = ProjDeskClient()
        with pytest.raises(ProjectNotFound) as exc_info:
            client.resolve("unknown")
        assert exc_info.value.project == "unknown"


def test_resolve_project_ambiguous():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 2

        client = ProjDeskClient()
        with pytest.raises(ProjectAmbiguous) as exc_info:
            client.resolve("api")
        assert exc_info.value.project == "api"


def test_resolve_unknown_exit_code():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 99
        mock_run.return_value.stderr = "unknown pd error"

        client = ProjDeskClient()
        with pytest.raises(ProjDeskError, match="unknown pd error"):
            client.resolve("something")


def test_resolve_timeout():
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["pd"], timeout=5)

        client = ProjDeskClient()
        with pytest.raises(ProjDeskError, match="did not respond"):
            client.resolve("something")


def test_resolve_pd_not_installed():
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = FileNotFoundError()

        client = ProjDeskClient()
        with pytest.raises(ProjDeskError, match="not installed"):
            client.resolve("something")
