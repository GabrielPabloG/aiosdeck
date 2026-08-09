"""Tests for the TUI interactive loop — key injection, page dispatch, fallback.

Exercises ``run_tui`` via the ``input_keys`` parameter to simulate keypress
sequences without a real TTY, and via ``monkeypatch`` to simulate non-TTY
fallback mode.
"""

from __future__ import annotations

import sys

import pytest

from aios.ui.tui import run_tui


class _RenderCapture:
    """Records every page name passed to it, returns a deterministic string."""

    def __init__(self) -> None:
        self.pages: list[str] = []

    def __call__(self, name: str) -> str:
        self.pages.append(name)
        return f"<<{name}>>"


class _RefreshCapture:
    """Records every refresh call."""

    def __init__(self) -> None:
        self.count = 0

    def __call__(self) -> None:
        self.count += 1


PAGE_NAMES = [
    "overview",
    "workflows",
    "agents",
    "skills",
    "knowledge",
    "usage",
    "quality",
    "settings",
]


class TestInputKeys:
    """Tests using the ``input_keys`` injection parameter."""

    def test_q_key_quits(self) -> None:
        capture = _RenderCapture()
        result = run_tui(capture, PAGE_NAMES, input_keys=["q"])
        assert result is None
        assert capture.pages == ["overview"]

    def test_r_key_refreshes_same_page(self) -> None:
        capture = _RenderCapture()
        result = run_tui(capture, PAGE_NAMES, input_keys=["r", "q"])
        assert result is None
        assert capture.pages == ["overview", "overview"]

    def test_number_key_switches_page(self) -> None:
        capture = _RenderCapture()
        result = run_tui(capture, PAGE_NAMES, input_keys=["3", "q"])
        assert result is None
        assert capture.pages == ["overview", "agents"]

    def test_number_1_stays_on_first_page(self) -> None:
        capture = _RenderCapture()
        result = run_tui(capture, PAGE_NAMES, input_keys=["1", "q"])
        assert result is None
        assert capture.pages == ["overview", "overview"]

    def test_number_8_switches_to_last_page(self) -> None:
        capture = _RenderCapture()
        result = run_tui(capture, PAGE_NAMES, input_keys=["8", "q"])
        assert result is None
        assert capture.pages == ["overview", "settings"]

    def test_tab_cycles_forward(self) -> None:
        capture = _RenderCapture()
        result = run_tui(capture, PAGE_NAMES, input_keys=["\t", "\t", "q"])
        assert result is None
        assert capture.pages == ["overview", "workflows", "agents"]

    def test_shift_tab_cycles_backward(self) -> None:
        capture = _RenderCapture()
        result = run_tui(capture, PAGE_NAMES, input_keys=["\x1b[Z", "q"])
        assert result is None
        assert capture.pages == ["overview", "settings"]

    def test_tab_wraps_around(self) -> None:
        capture = _RenderCapture()
        result = run_tui(capture, PAGE_NAMES, input_keys=["8", "\t", "q"])
        assert result is None
        assert capture.pages == ["overview", "settings", "overview"]

    def test_empty_keys_renders_once_and_exits(self) -> None:
        capture = _RenderCapture()
        result = run_tui(capture, PAGE_NAMES, input_keys=[])
        assert result is None
        assert capture.pages == ["overview"]

    def test_multiple_unknown_keys_stay_on_page(self) -> None:
        capture = _RenderCapture()
        result = run_tui(capture, PAGE_NAMES, input_keys=["x", "y", "q"])
        assert result is None
        assert capture.pages == ["overview", "overview", "overview"]


def test_empty_page_names_raises_value_error() -> None:
    capture = _RenderCapture()
    with pytest.raises(ValueError, match="page_names must not be empty"):
        run_tui(capture, [], input_keys=["q"])


def test_non_tty_fallback_renders_once_returns_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    capture = _RenderCapture()
    result = run_tui(capture, PAGE_NAMES)
    assert result == "<<overview>>"
    assert capture.pages == ["overview"]


class TestStartIndex:
    """Tests for the ``start_index`` parameter."""

    def test_starts_on_specified_page(self) -> None:
        capture = _RenderCapture()
        result = run_tui(capture, PAGE_NAMES, input_keys=["q"], start_index=3)
        assert result is None
        assert capture.pages == ["skills"]

    def test_start_index_on_last_page(self) -> None:
        capture = _RenderCapture()
        result = run_tui(capture, PAGE_NAMES, input_keys=["q"], start_index=7)
        assert result is None
        assert capture.pages == ["settings"]

    def test_invalid_start_index_raises(self) -> None:
        capture = _RenderCapture()
        with pytest.raises(ValueError, match="start_index=99"):
            run_tui(capture, PAGE_NAMES, start_index=99)

    def test_negative_start_index_raises(self) -> None:
        capture = _RenderCapture()
        with pytest.raises(ValueError, match="start_index=-1"):
            run_tui(capture, PAGE_NAMES, start_index=-1)


class TestRefresh:
    """Tests for the ``refresh`` callback parameter."""

    def test_refresh_not_called_without_r_key(self) -> None:
        capture = _RenderCapture()
        refresh = _RefreshCapture()
        result = run_tui(
            capture, PAGE_NAMES, input_keys=["q"], refresh=refresh
        )
        assert result is None
        assert refresh.count == 0

    def test_refresh_called_once_when_r_pressed(self) -> None:
        capture = _RenderCapture()
        refresh = _RefreshCapture()
        result = run_tui(
            capture, PAGE_NAMES, input_keys=["r", "q"], refresh=refresh
        )
        assert result is None
        assert refresh.count == 1

    def test_refresh_called_on_each_r_keypress(self) -> None:
        capture = _RenderCapture()
        refresh = _RefreshCapture()
        result = run_tui(
            capture, PAGE_NAMES, input_keys=["r", "r", "q"], refresh=refresh
        )
        assert result is None
        assert refresh.count == 2

    def test_refresh_called_after_page_navigation(self) -> None:
        capture = _RenderCapture()
        refresh = _RefreshCapture()
        result = run_tui(
            capture,
            PAGE_NAMES,
            input_keys=["3", "r", "q"],
            refresh=refresh,
        )
        assert result is None
        assert refresh.count == 1
        assert capture.pages == ["overview", "agents", "agents"]
