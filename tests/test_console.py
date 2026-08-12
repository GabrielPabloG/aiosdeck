"""Tests for aios.core.console — spinner, progress bar, and kanban board output."""

import os
import threading
from unittest.mock import patch

from aios.core.console import (
    CLEAR_LINE,
    KANBAN_COLUMNS,
    ProgressBar,
    ProgressSpinner,
    _fit_message,
    render_bar,
    render_kanban,
)

TERM_WIDTH = 30


class _FakeStream:
    def __init__(self) -> None:
        self.writes: list[str] = []
        self._tty = False

    def isatty(self) -> bool:
        return self._tty

    def write(self, text: str) -> None:
        self.writes.append(text)

    def flush(self) -> None:
        pass


def test_progress_spinner_non_tty_writes_static_line():
    stream = _FakeStream()
    with ProgressSpinner("Building", stream=stream):
        pass
    assert stream.writes == ["Building...\n"]


def test_fit_message_keeps_short():
    assert _fit_message("Hi", 20) == "Hi"


def test_fit_message_truncates_long():
    assert _fit_message("x" * 100, 30) == "x" * 27 + "…"


def test_fit_message_narrow_width():
    assert _fit_message("x" * 10, 2) == "…"


def test_spin_uses_clear_line_and_truncates():
    stream = _FakeStream()
    stream._tty = True
    spinner = ProgressSpinner("x" * 100, stream=stream)

    with (
        patch(
            "aios.core.console.shutil.get_terminal_size",
            return_value=os.terminal_size((TERM_WIDTH, 24)),
        ),
        patch("aios.core.console.time.sleep", side_effect=lambda _: spinner._stop.set()),
    ):
        spinner._spin()

    assert len(stream.writes) == 1
    line = stream.writes[0]
    assert line.startswith("\r" + CLEAR_LINE)
    visible = line.removeprefix("\r" + CLEAR_LINE)
    assert len(visible) <= TERM_WIDTH


def test_exit_clears_line():
    stream = _FakeStream()
    stream._tty = True
    spinner = ProgressSpinner("Working", stream=stream)

    with (
        patch("aios.core.console.time.sleep", side_effect=lambda _: spinner._stop.set()),
        spinner,
    ):
        pass

    assert stream.writes[-1] == "\r" + CLEAR_LINE


def test_render_bar_half_filled():
    bar = render_bar(0.5, 12)
    assert bar == "██████░░░░░░"
    assert len(bar) == 12


def test_render_bar_clamps():
    assert render_bar(1.5, 10) == "██████████"
    assert render_bar(-0.5, 10) == "░░░░░░░░░░"
    assert render_bar(0.0, 8) == "░░░░░░░░"
    assert render_bar(1.0, 8) == "████████"


def test_progress_bar_advances_indeterminate_frame():
    stream = _FakeStream()
    stream._tty = True
    bar = ProgressBar(sample_total=3, stream=stream)
    bar._report_phase_start("plan")

    with patch.object(bar, "_stop", threading.Event()):
        bar._stop.set()
        bar._animate()
        bar._animate()
        bar._animate()

    assert len(stream.writes) >= 1


def test_progress_bar_falls_back_when_not_tty():
    stream = _FakeStream()
    bar = ProgressBar(sample_total=1, stream=stream)
    bar._report_phase_start("plan")
    bar._report_phase_end("plan", 51200.0)
    bar._advance_sample()
    bar._finish()

    combined = "".join(stream.writes)
    assert "plan" in combined


def test_progress_bar_set_sample_total_updates():
    stream = _FakeStream()
    bar = ProgressBar(sample_total=1, stream=stream)
    bar.set_sample_total(3)
    assert bar._sample_total == 3


def test_progress_bar_set_phase_label_updates():
    stream = _FakeStream()
    bar = ProgressBar(sample_total=1, stream=stream)
    bar.set_phase_label("reviewer")
    assert bar._phase_label == "reviewer"


def test_render_kanban_always_shows_all_columns():
    output = render_kanban({"Done": 6})
    assert output == "  Backlog (0) | Todo (0) | InProgress (0) | Review (0) | Done (6)"


def test_render_kanban_empty_board():
    output = render_kanban({})
    assert output == "  Backlog (0) | Todo (0) | InProgress (0) | Review (0) | Done (0)"


def test_render_kanban_reflects_card_position():
    output = render_kanban({"Todo": 1})
    assert "Backlog (0)" in output
    assert "Todo (1)" in output
    assert all(column in output for column in KANBAN_COLUMNS)
