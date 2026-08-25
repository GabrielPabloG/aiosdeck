"""TTY-mode write sequences for ProgressSpinner and ProgressBar."""

import os
import threading
from unittest import mock

from aios.core.console import CLEAR_LINE, SPINNER_FRAMES, ProgressBar, ProgressSpinner


class _Stream:
    def __init__(self, tty: bool = True) -> None:
        self.writes = []
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty

    def write(self, text: str) -> None:
        self.writes.append(text)

    def flush(self) -> None:
        pass


class _DummyThread:
    def __init__(self) -> None:
        self.joins = []
        self.started = False

    def start(self) -> None:
        self.started = True

    def join(self, timeout=None) -> None:
        self.joins.append(timeout)


def _terminal(width: int):
    return mock.patch(
        "aios.core.console.shutil.get_terminal_size",
        return_value=os.terminal_size((width, 24)),
    )


def _make_bar(sample_total: int = 4, label: str = ""):
    stream = _Stream()
    with mock.patch("aios.core.console.threading.Thread") as thread_cls:
        dummy = _DummyThread()
        thread_cls.return_value = dummy
        bar = ProgressBar(sample_total, label=label, stream=stream)
    return bar, stream, thread_cls, dummy


def test_spinner_default_message_is_empty():
    stream = _Stream(tty=False)
    with ProgressSpinner(stream=stream):
        pass
    assert stream.writes == ["...\n"]


def test_spinner_tty_starts_daemon_animation_thread():
    stream = _Stream()
    spinner = ProgressSpinner("Job", stream=stream)
    wrote = threading.Event()

    def _sleep(_seconds):
        wrote.set()
        spinner._stop.set()

    with (
        _terminal(40),
        mock.patch("aios.core.console.time.sleep", side_effect=_sleep),
        spinner,
    ):
        assert spinner._thread is not None
        assert spinner._thread.daemon is True
        assert wrote.wait(timeout=2.0)

    frame_writes = [w for w in stream.writes if w.startswith("\r" + CLEAR_LINE)]
    assert frame_writes and "Job" in frame_writes[0]
    assert stream.writes[-1] == "\r" + CLEAR_LINE


def test_spinner_exit_joins_thread_with_short_timeout():
    stream = _Stream()
    spinner = ProgressSpinner("Job", stream=stream)
    joins = []
    real_join = threading.Thread.join

    def spy(thread_self, timeout=None):
        if thread_self is spinner._thread:
            joins.append(timeout)
        return real_join(thread_self, timeout)

    with (
        _terminal(40),
        mock.patch("aios.core.console.time.sleep", side_effect=lambda _: spinner._stop.set()),
        mock.patch.object(threading.Thread, "join", spy),
        spinner,
    ):
        pass

    assert joins == [0.3]


def test_spin_writes_frame_sequence_with_sleep_interval():
    stream = _Stream()
    spinner = ProgressSpinner("Work", stream=stream)
    sleeps = []

    def _sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 3:
            spinner._stop.set()

    with (
        _terminal(60),
        mock.patch("aios.core.console.time.sleep", side_effect=_sleep),
    ):
        spinner._spin()

    assert sleeps == [0.08, 0.08, 0.08]
    assert stream.writes[0] == f"\r{CLEAR_LINE}{SPINNER_FRAMES[0]} Work"
    assert stream.writes[1] == f"\r{CLEAR_LINE}{SPINNER_FRAMES[1]} Work"
    assert stream.writes[2] == f"\r{CLEAR_LINE}{SPINNER_FRAMES[2]} Work"


def test_progress_bar_spawns_animator_thread_on_tty():
    stream = _Stream()
    with mock.patch("aios.core.console.threading.Thread") as thread_cls:
        dummy = _DummyThread()
        thread_cls.return_value = dummy
        bar = ProgressBar(4, label="L", stream=stream)

    kwargs = thread_cls.call_args.kwargs
    assert kwargs["daemon"] is True
    assert kwargs["target"] == bar._animate
    assert dummy.started is True


def test_initial_redraw_shows_zero_progress_without_phase():
    bar, stream, _, _ = _make_bar(sample_total=4, label="Load")
    bar._advance_sample()

    bar._redraw()

    line = stream.writes[-1]
    assert "\n" not in line
    assert line == f"\r{CLEAR_LINE}Load {'█' * 3}{'░' * 9} 1/4"


def test_redraw_without_label_has_empty_prefix():
    bar, stream, _, _ = _make_bar(sample_total=1)

    bar._redraw()

    assert stream.writes[-1] == f"\r{CLEAR_LINE}{'░' * 12} 0/1"


def test_default_label_is_empty():
    stream = _Stream()
    with mock.patch("aios.core.console.threading.Thread") as thread_cls:
        thread_cls.return_value = _DummyThread()
        bar = ProgressBar(2, stream=stream)

    bar._redraw()

    assert stream.writes[-1] == f"\r{CLEAR_LINE}{'░' * 12} 0/2"


def test_redraw_honors_custom_bar_width():
    bar, stream, _, _ = _make_bar(sample_total=4)
    bar._bar_width = 8

    bar._redraw()

    assert stream.writes[-1] == f"\r{CLEAR_LINE}{'░' * 8} 0/4"


def test_phase_line_uses_first_spinner_frame_initially():
    bar, stream, _, _ = _make_bar(sample_total=2)
    bar._report_phase_start("plan")

    bar._redraw()

    assert stream.writes[-1] == f"\r{CLEAR_LINE}{'░' * 12} 0/2\n{CLEAR_LINE}  ⠋ plan...\r\033[A"


def test_active_phase_without_label_renders_bare_frame():
    bar, stream, _, _ = _make_bar(sample_total=2)
    bar._phase_active = True

    bar._redraw()

    assert stream.writes[-1].endswith(f"\n{CLEAR_LINE}  ⠋ ...\r\033[A")


def test_advance_sample_increments_by_one():
    bar, _, _, _ = _make_bar(sample_total=5)
    bar._advance_sample()
    bar._advance_sample()
    assert bar._sample_current == 2


def test_set_sample_total_floors_at_one():
    bar, _, _, _ = _make_bar(sample_total=3)
    bar.set_sample_total(1)
    assert bar._sample_total == 1


def test_set_phase_label_activates_phase_line():
    bar, stream, _, _ = _make_bar(sample_total=2)
    bar.set_phase_label("reviewer")

    bar._redraw()

    assert "reviewer..." in stream.writes[-1]


def test_animate_advances_tick_once_per_iteration():
    bar, stream, _, _ = _make_bar(sample_total=2)
    bar.set_phase_label("x")
    checks = iter([False, False, True])
    sleeps = []

    with (
        mock.patch.object(bar._stop, "is_set", side_effect=lambda: next(checks)),
        mock.patch("aios.core.console.time.sleep", side_effect=sleeps.append),
    ):
        bar._animate()

    assert bar._phase_ticks == 2
    assert sleeps == [0.08, 0.08]
    assert len(stream.writes) == 2


def test_report_phase_end_writes_summary_and_deactivates_phase():
    bar, stream, _, _ = _make_bar(sample_total=2)
    bar.set_phase_label("plan")

    bar._report_phase_end("plan", 60000.0)

    summary = stream.writes[1]
    assert summary == f"\n{CLEAR_LINE}  ✓ plan (60.0s)\n"

    bar._redraw()
    assert len(stream.writes) == 3
    assert "\n" not in stream.writes[-1]


def test_finish_clears_phase_lines_and_joins_animator():
    bar, stream, _, dummy = _make_bar(sample_total=2)
    bar.set_phase_label("plan")

    bar._finish()

    assert stream.writes == ["\r" + CLEAR_LINE, "\n" + CLEAR_LINE, "\r\033[A"]
    assert dummy.joins == [0.3]


def test_finish_is_noop_without_tty():
    stream = _Stream(tty=False)
    ProgressBar(1, stream=stream)._finish()
    assert stream.writes == []
