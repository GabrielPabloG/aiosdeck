"""Quality CLI — read-side for quality gate telemetry.

``aios quality stats`` renders the telemetry_gates table (aggregate stats or
raw records). Read-only: decisions are configured, never driven from the CLI.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

from aios.core.console import render_section


def cmd_quality_stats(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    filters = _parse_filters(raw_args or [])

    kernel = kernel_factory(project_path)
    kernel.start()

    engine = kernel.get_engine("telemetry")
    if engine is None:
        print("Telemetry engine not available.")
        return

    if filters.get("records"):
        rows = engine.query_gate_records(
            gate=filters.get("gate"),
            status=filters.get("status"),
            limit=filters.get("limit", 100),
        )
    else:
        rows = engine.query_gate_stats(
            gate=filters.get("gate"),
            status=filters.get("status"),
            limit=filters.get("limit", 100),
        )

    if filters.get("json"):
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return

    if filters.get("records"):
        _render_records(rows)
    else:
        _render_stats(rows)


def _parse_filters(raw_args: list[str]) -> dict:
    filters: dict = {"limit": 100}
    i = 0
    while i < len(raw_args):
        arg = raw_args[i]
        if arg == "--json":
            filters["json"] = True
        elif arg == "--records":
            filters["records"] = True
        elif arg in ("--gate", "--status"):
            i += 1
            if i < len(raw_args):
                filters[arg[2:]] = raw_args[i]
        elif arg == "--limit":
            i += 1
            if i < len(raw_args):
                filters["limit"] = int(raw_args[i])
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}", file=sys.stderr)
            _print_usage()
        i += 1
    return filters


def _print_usage() -> None:
    print(
        "Usage: aios quality stats [--gate NAME] [--status STATUS] "
        "[--limit N] [--records] [--json]",
        file=sys.stderr,
    )
    sys.exit(1)


def _render_stats(stats: list[dict]) -> None:
    print(render_section("Quality Gates"))
    if not stats:
        print("  No quality gate records found.")
        return
    for stat in stats:
        print(
            f"  {stat['gate']:<20} {stat['runs']} runs | "
            f"{stat['passed']} passed | {stat['failed']} failed | "
            f"{stat['skipped']} skipped | {stat['blocked']} blocked | "
            f"{stat['overridden']} overridden"
        )
        print(
            f"    findings: low={stat['findings_low']} "
            f"medium={stat['findings_medium']} "
            f"high={stat['findings_high']} "
            f"critical={stat['findings_critical']}"
        )
        if stat.get("avg_duration_ms") is not None:
            print(f"    avg duration: {stat['avg_duration_ms']:.0f}ms")


def _render_records(rows: list[dict]) -> None:
    print(render_section("Quality Gate Records"))
    if not rows:
        print("  No quality gate records found.")
        return
    for row in rows:
        print(
            f"  {row['timestamp']} {row['gate']:<20} {row['status']:<8} "
            f"blocked={row['blocked']} overridden={row['overridden']}"
        )
        print(
            f"    findings: low={row['findings_low']} "
            f"medium={row['findings_medium']} "
            f"high={row['findings_high']} "
            f"critical={row['findings_critical']}"
        )
