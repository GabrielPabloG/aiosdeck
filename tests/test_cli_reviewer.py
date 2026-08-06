"""Tests for the `aios review` CLI command — subprocess integration + fast unit tests."""

import json
import subprocess
from pathlib import Path

import pytest

from aios.agents.reviewer import ReviewerAgent
from aios.cli.commands import COMMANDS, _cmd_review
from aios.core import Kernel

FIXTURE = Path(__file__).parent / "fixtures" / "simple_repo"


def _kernel_with_reviewer(project_path) -> Kernel:
    kernel = Kernel(project_path=str(project_path))
    kernel.register(ReviewerAgent())
    return kernel


def test_review_subcommand_registered():
    assert "review" in COMMANDS
    assert COMMANDS["review"].execute is not None


def test_review_cli_json_output(capsys, tmp_path):
    _cmd_review(
        [str(FIXTURE), "--output", "json", "--dry-run"],
        tmp_path,
        _kernel_with_reviewer,
    )
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert set(data) == {"items", "stats", "summary"}
    assert isinstance(data["items"], list)


def test_review_cli_default_target_cwd(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "mod.py").write_text("# TODO: fix\n", encoding="utf-8")
    _cmd_review([], tmp_path, _kernel_with_reviewer)
    captured = capsys.readouterr()
    assert "Found" in captured.out
    assert "TODO" in captured.out


def test_review_cli_invalid_level_exits(capsys, tmp_path):
    with pytest.raises(SystemExit) as exc_info:
        _cmd_review(["--level", "bogus"], tmp_path, _kernel_with_reviewer)
    assert exc_info.value.code == 1
    assert "--level must be one of" in capsys.readouterr().err


def test_review_cli_writes_report_file(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _cmd_review([str(FIXTURE), "--output", "file"], tmp_path, _kernel_with_reviewer)
    captured = capsys.readouterr()
    assert "Wrote report" in captured.out
    report = json.loads((tmp_path / "reviewer_report.json").read_text(encoding="utf-8"))
    assert "items" in report and "stats" in report


def test_review_cli_diff_flag_non_git_repo(capsys, tmp_path):
    _cmd_review(
        [str(FIXTURE), "--diff", "--output", "json", "--dry-run"],
        tmp_path,
        _kernel_with_reviewer,
    )
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "items" in data


def test_review_cli_subprocess_integration():
    result = subprocess.run(
        ["aios", "review", str(FIXTURE), "--output", "json", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert set(data) >= {"items", "stats", "summary"}
