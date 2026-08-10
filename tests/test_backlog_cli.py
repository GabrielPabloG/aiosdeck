"""Tests for backlog CLI commands."""

from pathlib import Path

import pytest

from aios.cli.commands import COMMANDS


def test_backlog_command_registered():
    assert "backlog" in COMMANDS


def test_backlog_has_subcommands():
    backlog = COMMANDS["backlog"]
    assert "run" in backlog.subcommands
    assert "list" in backlog.subcommands
    assert "add" in backlog.subcommands
    assert "stats" in backlog.subcommands


class _MockKernel:
    def __init__(self) -> None:
        self._engines: dict = {}
        self._started = False

    def start(self) -> None:
        self._started = True

    def get_engine(self, name: str):
        return self._engines.get(name)

    def get_context(self):
        return None


def test_cmd_backlog_run_no_source(capsys):
    from aios.backlog.cli import cmd_backlog_run

    with pytest.raises(SystemExit) as exc:
        cmd_backlog_run([], Path("/tmp"), lambda p: _MockKernel())
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Usage:" in captured.out


class _RecordKernel:
    def __init__(self) -> None:
        self.last_create_branch = None
        self._engines: dict = {}

    def start(self) -> None:
        pass

    def get_engine(self, name: str):
        return self._engines.get(name)

    def get_context(self):
        return None

    def run(self, task, context, mode="plan", commit_factory=None, create_branch=False):
        self.last_create_branch = create_branch
        return _RunResult()


class _RunResult:
    success = True
    errors = ()
    stages = ()


def _write_todo(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _assert_create_branch(tmp_path: Path, flag: str, expected: bool) -> None:
    from aios.backlog.cli import cmd_backlog_run

    kernel = _RecordKernel()
    todo = tmp_path / "TODO.md"
    _write_todo(todo, ["- [ ] feat(cli): add flag"])
    args = [f"--source=file:{todo.name}", flag] if flag else [f"--source=file:{todo.name}"]
    cmd_backlog_run(args, tmp_path, lambda p: kernel)
    assert kernel.last_create_branch is expected


def test_cmd_backlog_run_branch_flag_defaults_false(tmp_path):
    _assert_create_branch(tmp_path, "", False)


def test_cmd_backlog_run_branch_flag_true(tmp_path):
    _assert_create_branch(tmp_path, "--branch", True)


def test_cmd_backlog_run_branch_flag_false(tmp_path):
    _assert_create_branch(tmp_path, "--no-branch", False)


def test_cmd_backlog_stats_no_records(capsys):
    from aios.backlog.cli import cmd_backlog_stats

    kernel = _MockKernel()

    class _FakeTelemetry:
        def query_backlog_stats(self, **kwargs):
            return []

    kernel._engines["telemetry"] = _FakeTelemetry()
    cmd_backlog_stats([], Path("/tmp"), lambda p: kernel)
    captured = capsys.readouterr()
    assert "No backlog runs recorded" in captured.out


def test_cmd_backlog_add_without_title(capsys):
    from aios.backlog.cli import cmd_backlog_add

    with pytest.raises(SystemExit) as exc:
        cmd_backlog_add([], Path("/tmp"), lambda p: _MockKernel())
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Usage:" in captured.out
