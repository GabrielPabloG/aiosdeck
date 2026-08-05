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


def _fit_message(message: str, width: int) -> str:
    """Truncate a message so it fits on one line, leaving room for the spinner frame."""
    available = max(1, width - 2)
    if len(message) > available:
        return message[: available - 1] + "…"
    return message


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
    """Render kanban columns with per-column card counts."""
    cells = [f"{name} ({summary.get(name, 0)})" for name in KANBAN_COLUMNS]
    return "  " + " | ".join(cells)
