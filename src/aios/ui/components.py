"""Composable console widgets — panels, tables, progress and status.

Every component consumes semantic theme tokens exclusively through a
``ColorResolver``; callers never pass raw ANSI codes or hex colors. Layout
is chosen from ``RenderContext.compact``, so the same widget renders a
spacious or condensed form based on the available terminal.
"""

from __future__ import annotations

from dataclasses import dataclass

from aios.ui.render import fit, is_compact, rule
from aios.ui.resolver import ColorResolver

_FILL = "█"
_EMPTY = "░"


@dataclass(frozen=True)
class RenderContext:
    """Injected rendering state shared by all widgets.

    ``compact`` is derived from ``width``/``height`` via ``is_compact``
    when not explicitly provided, so callers can either trust the terminal
    geometry or force a layout.
    """

    width: int = 80
    height: int = 24
    resolver: ColorResolver | None = None
    compact: bool | None = None

    def __post_init__(self) -> None:
        if self.resolver is None:
            raise TypeError("RenderContext requires a ColorResolver")
        if self.compact is None:
            object.__setattr__(self, "compact", is_compact(self.width, self.height))


def _edge(context: RenderContext, text: str, border: str) -> str:
    """Paint a border glyph sequence with a semantic token."""
    return context.resolver.paint(text, fg=border)


def render_panel(
    context: RenderContext,
    title: str = "",
    body: str = "",
    border: str = "default",
) -> str:
    """Render a bordered panel; compact form collapses to a single line."""
    resolver = context.resolver
    if context.compact:
        label = title or body
        if title and body:
            label = f"{title} {body}"
        return resolver.paint(label, fg=border)
    inner = max(0, context.width - 2)
    lines = [_edge(context, f"┌{'─' * inner}┐", border)]
    if title:
        lines.append(_edge(context, f"│ {fit(title, inner - 1):<{inner - 1}}│", border))
    for part in str(body).splitlines():
        lines.append(_edge(context, f"│ {fit(part, inner - 1):<{inner - 1}}│", border))
    lines.append(_edge(context, f"└{'─' * inner}┘", border))
    return "\n".join(lines)


def render_progress(
    context: RenderContext,
    label: str,
    fraction: float,
    tone: str = "info",
    width: int | None = None,
) -> str:
    """Render a labeled progress bar; compact form drops the bar."""
    frac = max(0.0, min(1.0, fraction))
    percent = f"{frac * 100:.0f}%"
    if context.compact:
        return f"{label} {percent}"
    bar_len = width if width is not None else 20
    filled = int(round(frac * bar_len))
    bar = _FILL * filled + _EMPTY * (bar_len - filled)
    return f"{label} {context.resolver.paint(bar, fg=tone)} {percent}"


def render_status_pill(context: RenderContext, text: str, tone: str = "info") -> str:
    """Render a status pill; compact form uses brackets instead of fill."""
    resolver = context.resolver
    if context.compact:
        return resolver.paint(f"<{text}>", fg=tone)
    return resolver.paint(f" {text} ", bg=tone)


def render_metric_card(
    context: RenderContext,
    label: str,
    value: str,
    tone: str = "info",
) -> str:
    """Render a metric card; compact form collapses to a single line."""
    resolver = context.resolver
    if context.compact:
        return resolver.paint(f"{label}: {value}", fg=tone)
    inner = max(0, context.width - 2)
    content = f"{label}: {value}"
    top = _edge(context, f"┌{'─' * inner}┐", tone)
    mid = (
        resolver.paint("│", fg=tone)
        + f" {fit(content, inner - 1):<{inner - 1}}"
        + resolver.paint("│", fg=tone)
    )
    bot = _edge(context, f"└{'─' * inner}┘", tone)
    return "\n".join((top, mid, bot))


def render_section_header(context: RenderContext, title: str, tone: str = "info") -> str:
    """Render a section title with a rule; compact form is a short marker."""
    resolver = context.resolver
    if context.compact:
        return resolver.paint(f"· {title}", fg=tone)
    bar = resolver.paint(rule("─", context.width), fg="default")
    return f"{resolver.paint(title, fg=tone)}\n{bar}"


def render_table(
    context: RenderContext,
    headers: list[str],
    rows: list[list[str]],
    tone: str = "info",
) -> str:
    """Render an aligned table; compact form drops the header rule."""
    if not headers:
        return ""
    resolver = context.resolver
    grid = [headers, *([list(r) for r in rows] if rows else [])]
    ncols = len(headers)
    padded = [row[:ncols] + [""] * (ncols - len(row)) for row in grid]
    widths = []
    for col in range(ncols):
        widths.append(max(len(padded[row][col]) for row in range(len(padded))))
    sep = "  " if not context.compact else " "

    def fmt(items: list[str]) -> str:
        return sep.join(str(items[i]).ljust(widths[i]) for i in range(ncols))

    header = fmt(padded[0])
    body = [fmt(row) for row in padded[1:]]
    if context.compact:
        return resolver.paint(header, fg=tone) + ("\n" + "\n".join(body) if body else "")
    output = [resolver.paint(header, fg=tone)]
    bar = "─" * (sum(widths) + len(sep) * (ncols - 1))
    output.append(resolver.paint(bar, fg="default"))
    output.extend(body)
    return "\n".join(output)
