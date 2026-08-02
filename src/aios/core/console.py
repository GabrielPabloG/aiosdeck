"""Dashboard rendering — separate from kernel logic."""

from aios import __version__

HEADER_BAR = "─" * 30


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
