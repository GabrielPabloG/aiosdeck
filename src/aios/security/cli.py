"""Security CLI — read-side for policy and the allow/deny audit trail.

``aios policy show`` renders the canonical capabilities per agent, the safe
default intents, and the additive capability→action expansion table. It is
static and read-only. ``aios security stats`` queries the ``telemetry_security``
trail persisted by the telemetry engine — the audit trail is a query, not a log.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

from aios.core.console import log_step, render_section
from aios.security.actions import CAPABILITY_ACTIONS, DEFAULT_INTENTS
from aios.security.capabilities import CANONICAL_CAPABILITIES


def cmd_policy_show(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    as_json = "--json" in (raw_args or [])

    capabilities = {agent: sorted(caps) for agent, caps in CANONICAL_CAPABILITIES.items()}
    intents = {name: sorted(intent.actions) for name, intent in DEFAULT_INTENTS.items()}
    expansion = {capability: sorted(actions) for capability, actions in CAPABILITY_ACTIONS.items()}

    if as_json:
        print(
            json.dumps(
                {
                    "capabilities": capabilities,
                    "intents": intents,
                    "expansion": expansion,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    print(render_section("Agent Capabilities"))
    for agent in sorted(capabilities):
        print(f"  {agent:<16} {', '.join(capabilities[agent])}")

    print(render_section("Default Intents"))
    for name in sorted(intents):
        print(f"  {name:<12} {', '.join(intents[name])}")
    print("\n  release: no default — requires an explicit intent override")

    print(render_section("Capability Expansion"))
    for capability in sorted(expansion):
        print(f"  {capability:<16} -> {', '.join(expansion[capability])}")
    print("\n  unknown capability -> grants nothing (fail-safe)")


def cmd_security_stats(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    filters = _parse_security_filters(raw_args or [])

    kernel = kernel_factory(project_path)
    kernel.start()

    engine = kernel.get_engine("telemetry")
    if engine is None:
        print("Telemetry engine not available.")
        return

    if filters.get("records"):
        rows = engine.query_security_records(
            decision=filters.get("decision"),
            agent=filters.get("agent"),
            limit=filters.get("limit", 100),
        )
    else:
        rows = engine.query_security_stats(
            decision=filters.get("decision"),
            agent=filters.get("agent"),
            limit=filters.get("limit", 100),
        )

    if filters.get("json"):
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return

    if filters.get("records"):
        _render_security_records(rows)
    else:
        _render_security_stats(rows)


def _parse_security_filters(raw_args: list[str]) -> dict:
    filters: dict = {"limit": 100}
    i = 0
    while i < len(raw_args):
        arg = raw_args[i]
        if arg == "--json":
            filters["json"] = True
        elif arg == "--records":
            filters["records"] = True
        elif arg in ("--decision", "--agent"):
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
        "Usage: aios security stats [--decision DECISION] [--agent AGENT] "
        "[--limit N] [--records] [--json]",
        file=sys.stderr,
    )
    sys.exit(1)


def _render_security_stats(stats: list[dict]) -> None:
    print(render_section("Security Decisions"))
    if not stats:
        print("  No security decisions recorded.")
        return
    for stat in stats:
        print(
            f"  {stat['decision']:<28} {stat['runs']} runs | "
            f"{stat['allowed']} allowed | {stat['denied']} denied"
        )


def _render_security_records(rows: list[dict]) -> None:
    print(render_section("Security Audit Records"))
    if not rows:
        print("  No security decisions recorded.")
        return
    for row in rows:
        verdict = "allow" if row["allowed"] else "deny"
        violations = ", ".join(row["violations"]) if row["violations"] else "-"
        print(
            f"  {row['timestamp']} {row['decision']:<28} "
            f"agent={row['agent']} {verdict} violations=[{violations}]"
        )


def _render_intent_summary(result) -> None:
    """Render the workflow intent and effective permissions per stage."""
    stages = [s for s in result.stages if s.details and "effective" in s.details]
    if not stages:
        return
    intent = next((s.details.get("intent") for s in stages if s.details.get("intent")), {})
    name = intent.get("name") or "unknown"
    source = intent.get("source") or "default"

    log_step("", f"intent: {name} (source: {source})")
    for stage in stages:
        log_step("", f"  {stage.name:<16} {', '.join(stage.details['effective'])}")
