"""CLI entry point for the ocean dashboard — parse flags, build render
closures, and dispatch to ``run_tui``.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aios.core.kernel import Kernel


def _error(msg: str) -> None:
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


_PAGE_DATA: dict[str, Callable[[Kernel], Any]] = {}


def _ensure_page_data() -> dict[str, Callable[[Kernel], Any]]:
    if not _PAGE_DATA:
        from aios.ui.datasources import (  # noqa: PLC0415
            agents_data,
            knowledge_data,
            overview_data,
            quality_data,
            settings_data,
            skills_data,
            usage_data,
            workflows_data,
        )

        _PAGE_DATA.update(
            {
                "overview": overview_data,
                "workflows": workflows_data,
                "agents": agents_data,
                "skills": skills_data,
                "knowledge": knowledge_data,
                "usage": usage_data,
                "quality": quality_data,
                "settings": settings_data,
            }
        )
    return _PAGE_DATA


def _parse_ocean_args(raw_args: list[str] | None) -> tuple[dict[str, Any], int | None]:
    opts: dict[str, Any] = {
        "page": "overview",
        "once": False,
        "json": False,
        "save": False,
    }
    refresh_interval: int | None = None

    i = 0
    while i < len(raw_args or []):
        arg = raw_args[i]
        if arg == "--once":
            opts["once"] = True
        elif arg == "--json":
            opts["json"] = True
        elif arg == "--save":
            opts["save"] = True
        elif arg == "--page":
            i += 1
            value = raw_args[i] if i < len(raw_args) else ""
            if not value:
                _error("--page requires a page name")
            opts["page"] = value
        elif arg == "--refresh":
            i += 1
            value = raw_args[i] if i < len(raw_args) else ""
            if not value:
                _error("--refresh requires a number of seconds")
            try:
                refresh_interval = int(value)
            except ValueError:
                _error("--refresh must be an integer")
            if refresh_interval is not None and refresh_interval < 1:
                _error("--refresh must be >= 1")
        elif arg.startswith("-"):
            _error(f"unknown option {arg}")
        else:
            _error(f"unexpected argument {arg}")
        i += 1

    return opts, refresh_interval


def cmd_ocean(
    raw_args: list[str],
    project_path: Path,
    kernel_factory: Callable,
) -> None:
    """Open the ocean dashboard — interactive TUI or single-shot output.

    Flags
    -----
    ``--page NAME``
        Start on the given page (default: ``"overview"``).
    ``--once``
        Render the selected page once and exit (no interactive loop).
    ``--json``
        Output the page data as JSON instead of rendering.
    ``--refresh N``
        Enable the refresh callback and re-fetch data every ``N`` seconds
        (parsed for forward compatibility; ``r`` key always reloads).
    ``--save``
        Persist the current ``ui`` section to ``~/.config/aiosdeck/config.yaml``.
        Never writes without this flag.
    """
    from aios.ui import (  # noqa: PLC0415
        PAGE_NAMES,
        ColorResolver,
        RenderContext,
        default_config_path,
        detect_color_mode,
        load_ui_section,
        ocean_theme,
        render_page,
        run_tui,
        save_ui_section,
    )

    opts, refresh_interval = _parse_ocean_args(raw_args)

    page = opts["page"]
    if page not in PAGE_NAMES:
        _error(f"unknown page {page!r}; choose from {', '.join(PAGE_NAMES)}")

    start_index = PAGE_NAMES.index(page)

    kernel = kernel_factory(project_path)
    kernel.start(render_dashboard=False)

    if opts["save"]:
        save_ui_section(default_config_path(), load_ui_section(default_config_path()))

    mode = detect_color_mode()
    resolver = ColorResolver(ocean_theme, mode)

    page_data = _ensure_page_data()

    if opts["json"]:
        show = page_data[page](kernel)
        print(json.dumps(show, indent=2, ensure_ascii=False, default=str))
        return

    def _render(name: str) -> str:
        return render_page(
            name,
            page_data[name](kernel),
            RenderContext(resolver=resolver),
        )

    if opts["once"]:
        print(_render(page))
        return

    result = run_tui(
        _render,
        PAGE_NAMES,
        start_index=start_index,
        refresh=None if refresh_interval is None else _noop_refresh,
    )
    if result is not None:
        print(result)


def _noop_refresh() -> None:
    pass
