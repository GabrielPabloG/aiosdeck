"""Tests for the ocean CLI command — flag parsing, rendering, JSON output, TUI dispatch."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from aios.ui.cli import _cmd_ocean


class FakeKernel:
    def __init__(self, project_path: str = ".") -> None:
        self.project_path = Path(project_path).resolve()

    def start(self, render_dashboard: bool = True) -> None:
        pass

    def status(self) -> dict[str, Any]:
        return {
            "project": str(self.project_path),
            "engines": {},
            "errors": [],
        }

    def get_engine(self, name: str) -> None:
        return None


def _fake_kernel_factory(path: Path) -> FakeKernel:
    return FakeKernel(project_path=str(path))


# ── --once ────────────────────────────────────────────────────────────────────


def test_cmd_ocean_once_renders_text(capsys: pytest.CaptureFixture) -> None:
    _cmd_ocean(["--once"], Path.cwd(), _fake_kernel_factory)
    captured = capsys.readouterr()
    out = captured.out
    assert "Project" in out
    assert "no engines" in out


# ── --json ────────────────────────────────────────────────────────────────────


def test_cmd_ocean_json_output(capsys: pytest.CaptureFixture) -> None:
    _cmd_ocean(["--json"], Path.cwd(), _fake_kernel_factory)
    captured = capsys.readouterr()
    out = captured.out
    parsed = json.loads(out)
    assert isinstance(parsed, dict)


# ── non-TTY fallback ──────────────────────────────────────────────────────────


def test_cmd_ocean_non_tty_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], int]] = []

    def _fake_run_tui(
        render: Any,
        page_names: list[str],
        *,
        input_keys: Any = None,
        start_index: int = 0,
        refresh: Any = None,
    ) -> str | None:
        calls.append((page_names, start_index))
        return render(page_names[0])

    monkeypatch.setattr("aios.ui.run_tui", _fake_run_tui)
    _cmd_ocean([], Path.cwd(), _fake_kernel_factory)
    assert len(calls) == 1
    page_names, start_index = calls[0]
    assert page_names[0] == "overview"
    assert start_index == 0


# ── --page flag ───────────────────────────────────────────────────────────────


def test_cmd_ocean_page_flag(capsys: pytest.CaptureFixture) -> None:
    _cmd_ocean(["--page", "workflows", "--once"], Path.cwd(), _fake_kernel_factory)
    captured = capsys.readouterr()
    out = captured.out
    assert "Workflows" in out


# ── dashboard regression ──────────────────────────────────────────────────────


def test_cmd_ocean_dashboard_unchanged_regression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], int, Any]] = []

    def _fake_run_tui(
        render: Any,
        page_names: list[str],
        *,
        input_keys: Any = None,
        start_index: int = 0,
        refresh: Any = None,
    ) -> str | None:
        calls.append((page_names, start_index, refresh))
        return None

    monkeypatch.setattr("aios.ui.run_tui", _fake_run_tui)
    _cmd_ocean([], Path.cwd(), _fake_kernel_factory)
    assert len(calls) == 1
    page_names, start_index, refresh = calls[0]
    assert "overview" in page_names
    assert start_index == 0
    assert refresh is None
