"""Routing CLI — model routing explain, stats, and records.

``aios route explain --agent A [--task-type T] [--complexity C] [--context-size N]``
``aios route stats [--agent A] [--model M] [--limit N] [--records] [--json]``
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

from aios.routing.engine import RuleBasedRouter
from aios.routing.models import RouteInput


def cmd_route_explain(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    opts = _parse_explain_args(raw_args)
    kernel = kernel_factory(project_path)
    kernel.start()

    config_engine = kernel.get_engine("config")
    routing_config = (
        config_engine.config.routing if config_engine and config_engine.config else None
    )
    if routing_config is None:
        print("Routing config not available.", file=sys.stderr)
        sys.exit(1)

    router = RuleBasedRouter(routing_config)
    route_input = RouteInput(
        agent=opts["agent"],
        task_type=opts.get("task_type", "code"),
        complexity=opts.get("complexity", "medium"),
        context_size=opts.get("context_size", 0),
    )
    decision = router.route(route_input)

    result = {
        "provider": decision.provider,
        "model": decision.model,
        "variant": decision.variant,
        "reason": decision.reason,
        "estimated_cost": decision.estimated_cost,
        "source": decision.source,
        "fallback_chain": decision.fallback_chain,
    }

    if opts.get("json"):
        print(json.dumps(result, indent=2))
        return

    print(f"Provider:       {result['provider']}")
    print(f"Model:          {result['model']}")
    if result["variant"]:
        print(f"Variant:        {result['variant']}")
    print(f"Reason:         {result['reason']}")
    print(f"Estimated cost: ${result['estimated_cost']:.6f}")
    print(f"Source:         {result['source']}")
    if result["fallback_chain"]:
        print("Fallback chain:")
        for fb in result["fallback_chain"]:
            line = f"  - {fb['provider']}/{fb['model']}"
            if fb.get("variant"):
                line += f" variant={fb['variant']}"
            print(line)


def cmd_route_stats(  # noqa: PLR0911
    raw_args: list[str], project_path: Path, kernel_factory: Callable
) -> None:
    opts = _parse_stats_args(raw_args)
    kernel = kernel_factory(project_path)
    kernel.start()

    telemetry = kernel.get_engine("telemetry")
    if telemetry is None:
        print("Telemetry engine not available.", file=sys.stderr)
        sys.exit(1)

    if opts.get("records"):
        records = telemetry.query_routing_records(
            agent=opts.get("agent"),
            model=opts.get("model"),
            date_from=opts.get("date_from"),
            date_to=opts.get("date_to"),
            limit=opts.get("limit", 100),
        )
        if opts.get("json"):
            print(json.dumps(records, indent=2, default=str))
            return

        if not records:
            print("No routing records found.")
            return

        print(f"Routing records ({len(records)}):")
        for r in records:
            fb = " [FALLBACK]" if r.get("fallback_used") else ""
            print(
                f"  [{r['timestamp'][:19]}] {r['agent']:<12} "
                f"{r['model']:<30} "
                f"${r['estimated_cost']:.6f} "
                f"({r['reason']}){fb}"
            )
        return

    if opts.get("accuracy"):
        accuracy = telemetry.query_route_accuracy(limit=opts.get("limit", 100))
        if opts.get("json"):
            print(json.dumps(accuracy, indent=2, default=str))
            return

        if not accuracy:
            print("No route accuracy data available.")
            return

        print(f"Route accuracy ({len(accuracy)} records):")
        for a in accuracy:
            delta_str = f"+${a['delta']:.6f}" if a["delta"] >= 0 else f"-${abs(a['delta']):.6f}"
            print(
                f"  {a['agent']:<12} {a['model']:<30} "
                f"est=${a['estimated_cost']:.6f} "
                f"act=${a['actual_cost']:.6f} "
                f"({delta_str})"
            )
        return

    stats = telemetry.query_routing_stats(
        agent=opts.get("agent"),
        model=opts.get("model"),
        date_from=opts.get("date_from"),
        date_to=opts.get("date_to"),
        limit=opts.get("limit", 100),
    )
    if opts.get("json"):
        print(json.dumps(stats, indent=2, default=str))
        return

    if not stats:
        print("No routing stats found.")
        return

    print(f"Routing stats ({len(stats)} groups):")
    for s in stats:
        print(
            f"  {s['agent']:<12} {s['model']:<30} "
            f"routes={s['routes']:<5} "
            f"fallbacks={s['fallbacks']:<5} "
            f"avg_cost=${s['avg_estimated_cost']:.6f} "
            f"avg_ctx={s['avg_context_size']:.0f}"
        )


def _parse_explain_args(raw_args: list[str]) -> dict:
    opts: dict = {"agent": "planner"}
    i = 0
    while i < len(raw_args):
        arg = raw_args[i]
        if arg == "--json":
            opts["json"] = True
        elif arg in ("--agent", "--task-type", "--complexity"):
            i += 1
            key = arg.lstrip("-").replace("-", "_")
            opts[key] = raw_args[i] if i < len(raw_args) else ""
        elif arg == "--context-size":
            i += 1
            opts["context_size"] = int(raw_args[i]) if i < len(raw_args) else 0
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}", file=sys.stderr)
            sys.exit(1)
        i += 1
    return opts


def _parse_stats_args(raw_args: list[str]) -> dict:
    opts: dict = {"limit": 100}
    i = 0
    while i < len(raw_args):
        arg = raw_args[i]
        if arg == "--json":
            opts["json"] = True
        elif arg == "--records":
            opts["records"] = True
        elif arg == "--accuracy":
            opts["accuracy"] = True
        elif arg in ("--agent", "--model", "--date-from", "--date-to"):
            i += 1
            key = arg.lstrip("-").replace("-", "_")
            opts[key] = raw_args[i] if i < len(raw_args) else ""
        elif arg == "--limit":
            i += 1
            opts["limit"] = int(raw_args[i]) if i < len(raw_args) else 100
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}", file=sys.stderr)
            sys.exit(1)
        i += 1
    return opts


def cmd_route(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    if not raw_args:
        print("Usage: aios route <subcommand>", file=sys.stderr)
        print()
        print("Subcommands:")
        print("  explain   Explain routing decision for a given input")
        print("  stats     Show routing telemetry stats or records")
        return

    sub_map = {
        "explain": cmd_route_explain,
        "stats": cmd_route_stats,
    }

    sub_name = raw_args[0]
    handler = sub_map.get(sub_name)
    if handler is None:
        print(f"Unknown subcommand: {sub_name}", file=sys.stderr)
        sys.exit(1)

    handler(raw_args[1:], project_path, kernel_factory)
