"""Core CLI commands — dashboard, doctor, init, help, exit, completion.

Extracted from the central registry. These commands handle
diagnostics, project initialization, help output, and lifecycle.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Callable
from pathlib import Path

from aios.cli.completion_scripts import BASH_COMPLETION, ZSH_COMPLETION

VERSION_TEXT = "AiosDeck"


def cmd_dashboard(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    kernel = kernel_factory(project_path)
    kernel.start(render_dashboard=False)

    from aios.ui import (  # noqa: PLC0415
        PAGE_NAMES,
        ColorResolver,
        RenderContext,
        detect_color_mode,
        ocean_theme,
        render_page,
        run_tui,
    )
    from aios.ui.datasources import PAGE_DATA  # noqa: PLC0415

    mode = detect_color_mode()
    resolver = ColorResolver(ocean_theme, mode)

    def _render(page_name: str) -> str:
        data = PAGE_DATA[page_name](kernel)
        return render_page(page_name, data, RenderContext(resolver=resolver))

    run_tui(_render, PAGE_NAMES)


def cmd_doctor(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    from aios.core.console import render_row, render_section  # noqa: PLC0415

    as_json = "--json" in (raw_args or [])

    kernel = kernel_factory(project_path)
    kernel.start()
    if hasattr(kernel, "diagnose_runtime"):
        kernel.diagnose_runtime()

    status = kernel.status()

    if as_json:
        context = kernel.get_context()
        if context:
            status["context"] = {
                "language": context.project.language,
                "linter": context.tools.linter,
                "formatter": context.tools.formatter,
                "test_runner": context.tools.test_runner,
                "git_branch": context.git.branch,
                "git_status": context.git.status,
                "opencode": context.runtime.opencode,
                "ai_jail": context.runtime.ai_jail,
            }
        print(json.dumps(status, indent=2))
        return

    logger = logging.getLogger("aios")
    context = kernel.get_context()
    if context:
        logger.info(render_section("Doctor"))
        logger.info(render_row("Language", context.project.language))
        logger.info(render_row("Tools", context.tools.linter or "none"))
        logger.info(render_row("Git", f"{context.git.branch} ({context.git.status})"))
        logger.info(
            render_row(
                "OpenCode",
                "installed" if context.runtime.opencode else "not found",
            )
        )
        logger.info(render_row("ai-jail", "installed" if context.runtime.ai_jail else "not found"))

    diagnostics = status.get("runtime_diagnostics")
    if diagnostics:
        logger.info(render_section("Runtime Diagnostics"))
        logger.info(render_row("Status", diagnostics["status"]))
        logger.info(render_row("Code", diagnostics["code"]))
        logger.info(render_row("Provider", diagnostics["provider"] or "not configured"))
        logger.info(render_row("Model", diagnostics["model"] or "not configured"))
        logger.info(render_row("Source", diagnostics["source"]))
        for suggestion in diagnostics["suggestions"]:
            logger.info(render_row("Suggestion", suggestion))

    errors = status.get("errors", [])
    if errors:
        logger.warning("\nWarnings:")
        for err in errors:
            logger.warning(f"  {err}")


def cmd_init(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    aios_dir = project_path / ".aios"
    aios_dir.mkdir(parents=True, exist_ok=True)

    yaml_path = aios_dir / "project.yaml"
    if not yaml_path.exists():
        yaml_path.write_text(
            "# .aios/project.yaml — Project manifest for AiosDeck\n"
            "# ProjDesk prepares the development environment.\n"
            "# AiosDeck prepares the intelligence environment.\n"
            "\n"
            f"name: {project_path.name}\n"
            "runtime: opencode\n"
            "sandbox: ai-jail\n"
            "\n"
            "skills:\n"
            "  - project-dna\n"
            "  - coding-style\n"
        )

    GITIGNORE_RULES = [".aios/memory.db"]

    gitignore_path = project_path / ".gitignore"
    existing_text = gitignore_path.read_text() if gitignore_path.exists() else ""
    existing_lines = existing_text.splitlines()

    new_lines = [rule for rule in GITIGNORE_RULES if rule not in existing_lines]
    if new_lines:
        with gitignore_path.open("a") as f:
            if existing_text and not existing_text.endswith("\n"):
                f.write("\n")
            for rule in new_lines:
                f.write(f"{rule}\n")

    print(f"Project initialized at {aios_dir}")


def cmd_help(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:  # noqa: ARG001
    from aios.cli.commands import _print_help  # noqa: PLC0415

    _print_help()


def cmd_complete(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    from aios.cli.completion import complete  # noqa: PLC0415

    suggestions = complete(raw_args)
    for s in suggestions:
        print(s)


def cmd_completion(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:  # noqa: ARG001
    """Print the shell completion script for bash or zsh.

    ``aios completion --bash`` and ``aios completion --zsh`` emit the
    corresponding completion script to stdout, so users can install it via
    ``source <(aios completion --bash)`` without shipping extra files.
    """
    args = raw_args or []
    if "--bash" in args:
        print(BASH_COMPLETION, end="")
    elif "--zsh" in args:
        print(ZSH_COMPLETION, end="")
    else:
        print("Usage: aios completion --bash | --zsh", file=sys.stderr)
        sys.exit(1)


def cmd_exit(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    kernel = kernel_factory(project_path)
    kernel.shutdown()
