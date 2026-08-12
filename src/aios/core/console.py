"""Dashboard rendering — separate from kernel logic."""

import shutil
import sys
import threading
import time
from typing import IO

from aios import __version__

HEADER_BAR = "─" * 30

SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

CLEAR_LINE = "\033[K"

KANBAN_COLUMNS = ("Backlog", "Todo", "InProgress", "Review", "Done")

BAR_WIDTH = 12
MARQUEE_WINDOW = 4


def _fit_message(message: str, width: int) -> str:
    """Truncate a message so it fits on one line, leaving room for the spinner frame."""
    available = max(1, width - 2)
    if len(message) > available:
        return message[: available - 1] + "…"
    return message


def render_bar(fraction: float, width: int = BAR_WIDTH) -> str:
    """Deterministic filled/empty bar for known progress."""
    filled = max(0, min(width, round(fraction * width)))
    return "\u2588" * filled + "\u2591" * (width - filled)


class ProgressSpinner:
    """Animated spinner rendered on one line while a job runs.

    Falls back to a single static line when the stream is not a TTY,
    so piped output stays clean and tests stay deterministic.
    """

    def __init__(self, message: str = "", stream: IO | None = None) -> None:
        self._message = message
        self._stream = stream or sys.stderr
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "ProgressSpinner":
        if self._stream.isatty():
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        else:
            self._stream.write(f"{self._message}...\n")
            self._stream.flush()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.3)
        if self._stream.isatty():
            self._stream.write("\r" + CLEAR_LINE)
            self._stream.flush()

    def _spin(self) -> None:
        index = 0
        while not self._stop.is_set():
            frame = SPINNER_FRAMES[index % len(SPINNER_FRAMES)]
            width = shutil.get_terminal_size().columns
            message = _fit_message(self._message, width)
            self._stream.write(f"\r{CLEAR_LINE}{frame} {message}")
            self._stream.flush()
            time.sleep(0.08)
            index += 1


def _marquee_bar(tick: int, width: int) -> str:
    """Indeterminate marquee bar — an animated window moved by ``tick``."""
    total = width + MARQUEE_WINDOW
    pos = tick % total
    cells = ["\u2591"] * width
    for i in range(MARQUEE_WINDOW):
        idx = (pos + i) % width
        cells[idx] = "\u2588"
    return "".join(cells)


class ProgressBar:
    """Two-line progress bar: sample (deterministic) + phase (indeterminate marquee).

    Writes to *stderr* with ANSI escape codes on TTYs. On non-TTY streams
    it delegates to ``log_step`` so piped/CI output stays clean.
    """

    def __init__(self, sample_total: int, label: str = "", stream: IO | None = None) -> None:
        self._sample_current = 0
        self._sample_total = max(sample_total, 1)
        self._label = label
        self._stream = stream or sys.stderr
        self._tty = self._stream.isatty()
        self._phase_active = False
        self._phase_label = ""
        self._phase_ticks = 0
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._bar_width = BAR_WIDTH
        if self._tty:
            self._thread = threading.Thread(target=self._animate, daemon=True)
            self._thread.start()

    def _animate(self) -> None:
        while not self._stop.is_set():
            self._phase_ticks += 1
            self._redraw()
            time.sleep(0.08)

    def _redraw(self) -> None:
        with self._lock:
            prefix = f"{self._label} " if self._label else ""
            fraction = self._sample_current / self._sample_total
            sbar = render_bar(fraction, self._bar_width)
            sample_label = f"sample {self._sample_current}/{self._sample_total}"
            line = f"\r{CLEAR_LINE}{prefix}{sbar} {sample_label}"
            if self._phase_active:
                pbar = _marquee_bar(self._phase_ticks, self._bar_width)
                line += f"\n{CLEAR_LINE}  {pbar} {self._phase_label}..."
                line += "\r\033[A"
            self._stream.write(line)
            self._stream.flush()

    def _advance_sample(self) -> None:
        with self._lock:
            self._sample_current += 1

    def set_sample_total(self, n: int) -> None:
        with self._lock:
            self._sample_total = max(n, 1)

    def set_phase_label(self, label: str) -> None:
        with self._lock:
            self._phase_label = label
            self._phase_active = True

    def _report_phase_start(self, label: str) -> None:
        with self._lock:
            self._phase_active = True
            self._phase_label = label

    def _report_phase_end(self, label: str, elapsed_ms: float) -> None:
        with self._lock:
            self._phase_active = False
            self._phase_label = ""
        self._redraw()
        seconds = elapsed_ms / 1000.0
        self._stream.write(f"\n{CLEAR_LINE}  \u2713 {label} ({seconds:.1f}s)\n")
        self._stream.flush()

    def _finish(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.3)
        if self._tty:
            self._stream.write("\r" + CLEAR_LINE)
            if self._phase_active:
                self._stream.write("\n" + CLEAR_LINE)
                self._stream.write("\r\033[A")
            self._stream.flush()


def render_header() -> str:
    return f"\n{HEADER_BAR}\n AiosDeck v{__version__}\n{HEADER_BAR}"


def render_footer() -> str:
    return HEADER_BAR


def render_row(label: str, value: str) -> str:
    return f" {label:<14} {value}"


def render_engine(engine_name: str, status: str) -> str:
    icon = "✓" if status == "ready" else "✗"
    return f" {engine_name.capitalize():<14} {icon} {status}"


def render_section(title: str) -> str:
    return f"\n {title}"


def log_step(icon: str, message: str) -> None:
    """Write a progress line with a status icon to stderr."""
    sys.stderr.write(f"{icon} {message}\n")
    sys.stderr.flush()


def render_kanban(summary: dict[str, int]) -> str:
    """Render kanban columns with per-column card counts.

    An optional ``Blocked`` key renders a trailing blocked-status cell.
    """
    cells = [f"{name} ({summary.get(name, 0)})" for name in KANBAN_COLUMNS]
    blocked = summary.get("Blocked", 0)
    if blocked:
        cells.append(f"⛔ Blocked ({blocked})")
    return "  " + " | ".join(cells)
