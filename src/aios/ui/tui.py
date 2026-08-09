"""TTY-aware interactive loop — raw keyboard navigation, injectable for tests.

Keys ``1..8`` switch pages, ``tab`` cycles forward, ``q`` quits, ``r``
refreshes the current view.  When ``input_keys`` is provided (testing) the
loop consumes that list instead of reading from stdin.  Non-TTY mode renders
once to stdout and exits immediately.
"""

from __future__ import annotations

import functools
import os
import select
import sys
import termios
import tty
from collections.abc import Callable, Sequence

_PAGE_KEYS = {str(i): i - 1 for i in range(1, 9)}
_CMD_QUIT = "q"
_CMD_REFRESH = "r"
_CMD_NEXT = "\t"
_CMD_PREV = "\x1b[Z"  # shift+tab

_MAX_KEYS = 16

_FOOTER = "q quit \u00b7 r refresh \u00b7 tab next"

_BACKUP = 100


def _read_keys_stdio(timeout: float | None = None) -> list[str]:
    """Block and read keypresses from stdin using termios/select.

    With ``timeout=None`` this blocks indefinitely until at least one key is
    pressed (no polling).  Returns a list of key strings (normally one, but
    multiple keys may arrive between reads).
    """
    fd = sys.stdin.fileno()
    try:
        attrs = termios.tcgetattr(fd)
    except termios.error:
        return []
    try:
        tty.setcbreak(fd)
        readable, _, _ = select.select([fd], [], [], timeout)
        if not readable:
            return []
        raw = os.read(fd, _MAX_KEYS)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
    return list(raw.decode("utf-8", errors="replace"))


def _read_keys_test(keys: list[str]) -> list[str]:
    """Pop one key from a test fixture list per call."""
    if not keys:
        return []
    key = keys.pop(0)
    return [key]


def _is_tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _dispatch_key(key: str, index: int, page_count: int) -> int | None:
    """Map a keypress to a new page index, or ``None`` to quit."""
    if key in _PAGE_KEYS:
        return _PAGE_KEYS[key]
    if key == _CMD_NEXT:
        return (index + 1) % page_count
    if key == _CMD_PREV:
        return (index - 1) % page_count
    if key == _CMD_QUIT:
        return None  # signal quit
    return index  # refresh (r) or unknown


def _draw(
    render: Callable[[str], str],
    index: int,
    page_names: Sequence[str],
    first: bool,
    footer: str | None,
) -> None:
    """Render the current page to stdout, clearing on redraws."""
    rendered = render(page_names[index])
    if not first:
        sys.stdout.write("\033[2J\033[H")
    text = f"{rendered}\n{footer}" if first and footer else rendered
    sys.stdout.write(text)
    sys.stdout.write("\n")
    sys.stdout.flush()


def _process_keys(
    keys: Sequence[str],
    index: int,
    page_count: int,
    refresh: Callable[[], None] | None,
) -> tuple[bool, int, bool]:
    """Dispatch a key batch, returning ``(quit, index, redraw)``."""
    quit_loop = False
    redraw = False
    for key in keys:
        new_index = _dispatch_key(key, index, page_count)
        if new_index is None:
            quit_loop = True
            break
        if key == _CMD_REFRESH and refresh is not None:
            refresh()
        index = new_index
        redraw = True
    return quit_loop, index, redraw


def run_tui(
    render: Callable[[str], str],
    page_names: Sequence[str],
    *,
    input_keys: list[str] | None = None,
    start_index: int = 0,
    refresh: Callable[[], None] | None = None,
) -> str | None:
    """Run the interactive TUI loop.

    Parameters
    ----------
    render:
        A callable that accepts a page name and returns its text output.
    page_names:
        Ordered list of available page identifiers.
    input_keys:
        When provided (testing), the loop reads from this list instead of
        stdin.  An empty list signals immediate EOF.
    start_index:
        Page index to start on (default 0).  Must be in ``range(len(page_names))``.
    refresh:
        Optional callback invoked before re-rendering when the user presses
        ``r``.  Useful for reloading underlying data.

    Returns
    -------
    str | None
        ``None`` when the loop ran interactively and the user quit with
        ``q``.  The rendered page string in non-TTY fallback mode (single
        render, no interaction).

    Raises
    ------
    ValueError
        When ``page_names`` is empty or ``start_index`` is out of range.
    """
    if not page_names:
        raise ValueError("page_names must not be empty")
    if not 0 <= start_index < len(page_names):
        raise ValueError(f"start_index={start_index} out of range for {len(page_names)} pages")

    index = start_index
    if input_keys is not None:
        read_keys: Callable[[], list[str]] = functools.partial(_read_keys_test, input_keys)
        footer = None
    else:
        read_keys = _read_keys_stdio
        footer = _FOOTER
    interactive = (input_keys is not None) or _is_tty()

    if not interactive:
        return render(page_names[0])

    sys.stderr.write("\n")
    sys.stderr.flush()

    first = True
    redraw = True

    while True:
        if redraw:
            _draw(render, index, page_names, first, footer)
            first = False
            redraw = False

        keys = read_keys()
        if not keys:
            if input_keys is not None:
                break
            continue

        quit_loop, index, redraw = _process_keys(keys, index, len(page_names), refresh)
        if quit_loop:
            return None
