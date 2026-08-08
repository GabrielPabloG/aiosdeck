"""Usage CLI — query telemetry data from the command line."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from aios.core.console import render_row, render_section


def cmd_usage(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    filters = _parse_filters(raw_args or [])

    kernel = kernel_factory(project_path)
    kernel.start()

    engine = kernel.get_engine("telemetry")
    if engine is None:
        print("Telemetry engine not available.")
        return

    data = engine.query(
        agent=filters.get("agent"),
        model=filters.get("model"),
        workflow_id=filters.get("workflow_id"),
        date_from=filters.get("date_from"),
        date_to=filters.get("date_to"),
        limit=filters.get("limit", 100),
    )

    if filters.get("json"):
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    _render_table(data)


def _parse_filters(raw_args: list[str]) -> dict:
    filters: dict = {"limit": 100}
    i = 0
    while i < len(raw_args):
        arg = raw_args[i]
        if arg == "--json":
            filters["json"] = True
        elif arg == "--today":
            now = datetime.now(UTC)
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            filters["date_from"] = start.isoformat()
            filters["date_to"] = now.isoformat()
        elif arg == "--agent":
            i, filters = _parse_value_arg(raw_args, i, filters, "agent")
        elif arg == "--model":
            i, filters = _parse_value_arg(raw_args, i, filters, "model")
        elif arg == "--workflow":
            i, filters = _parse_value_arg(raw_args, i, filters, "workflow_id")
        elif arg == "--from":
            i, filters = _parse_value_arg(raw_args, i, filters, "date_from")
        elif arg == "--to":
            i, filters = _parse_value_arg(raw_args, i, filters, "date_to")
        elif arg == "--limit":
            i += 1
            if i < len(raw_args):
                filters["limit"] = int(raw_args[i])
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}", file=sys.stderr)
            _print_usage_help()
        i += 1
    return filters


def _parse_value_arg(raw_args: list[str], i: int, filters: dict, key: str) -> tuple:
    i += 1
    if i < len(raw_args):
        filters[key] = raw_args[i]
    return i, filters


def _print_usage_help() -> None:
    print(
        "Usage: aios usage [--agent X] [--model Y] [--today] "
        "[--workflow Z] [--from DATE] [--to DATE] [--limit N] [--json]",
        file=sys.stderr,
    )
    sys.exit(1)


def _render_table(data: dict) -> None:
    totals = data.get("totals", {})
    by_agent = data.get("by_agent", {})
    by_model = data.get("by_model", {})
    records = data.get("records", [])
    cost_records = data.get("cost_records", [])

    print(render_section("Usage Summary"))
    print(render_row("Total input tokens", f"{totals.get('input_tokens', 0):,}"))
    print(render_row("Total output tokens", f"{totals.get('output_tokens', 0):,}"))
    print(render_row("Total tokens", f"{totals.get('total_tokens', 0):,}"))
    total_cost = totals.get("total_cost", 0)
    currency = totals.get("currency", "USD")
    print(render_row("Total cost", f"${total_cost:.4f} {currency}"))

    if by_agent:
        print(render_section("By Agent"))
        for agent_name in sorted(by_agent):
            a = by_agent[agent_name]
            print(f"  {agent_name:<20} {a['input_tokens']:,} in / {a['output_tokens']:,} out")

    if by_model:
        print(render_section("By Model"))
        for model_name in sorted(by_model):
            m = by_model[model_name]
            print(f"  {model_name:<20} {m['input_tokens']:,} in / {m['output_tokens']:,} out")

    priced = [c for c in cost_records if c.get("status") == "priced"]
    unpriced = [c for c in cost_records if c.get("status") == "unpriced"]

    if priced or unpriced:
        print(render_section("Costs"))
        if priced:
            total = sum(c.get("total_cost", 0) for c in priced)
            print(f"  Priced: {len(priced)} records, ${total:.4f}")
        if unpriced:
            print(f"  Unpriced: {len(unpriced)} records (no pricing data available)")

    if not records:
        print("\n  No usage records found.")
    else:
        print(f"\n  {len(records)} usage record(s) found.")
