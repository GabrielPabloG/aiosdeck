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
