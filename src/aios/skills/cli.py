"""Skills CLI — discover, inspect, and view skill lifecycle stats."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

from aios.core.console import render_row, render_section
from aios.skills.discovery import SkillDiscoveryService
from aios.skills.registry import SkillRegistry
from aios.skills.retrieval import SkillRetrievalService


def cmd_skills_discover(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    if not raw_args:
        print(
            "Usage: aios skills discover <intent> [--agent NAME] [--top N] [--json]",
            file=sys.stderr,
        )
        sys.exit(1)

    intent = raw_args[0]
    agent = "planner"
    top_k = 5
    as_json = False

    i = 1
    while i < len(raw_args):
        if raw_args[i] == "--json":
            as_json = True
        elif raw_args[i] == "--agent" and i + 1 < len(raw_args):
            agent = raw_args[i + 1]
            i += 1
        elif raw_args[i] == "--top" and i + 1 < len(raw_args):
            try:
                top_k = int(raw_args[i + 1])
            except ValueError:
                pass
            i += 1
        i += 1

    kernel = kernel_factory(project_path)
    kernel.start()

    registry = SkillRegistry(project_path)
    discovery = SkillDiscoveryService(registry, top_k=top_k)
    context = kernel.get_context()

    results = discovery.discover(intent, context)

    knowledge = kernel.get_engine("knowledge")
    if knowledge is not None and results:
        retrieval = SkillRetrievalService(knowledge)
        contexts = retrieval.retrieve(results, intent, agent=agent)
    else:
        contexts = []

    if as_json:
        output = {
            "intent": intent,
            "agent": agent,
            "candidates": len(results),
            "used": len(contexts),
            "skills": [
                {
                    "name": r.skill.name,
                    "score": r.score,
                    "trigger_matches": r.trigger_matches,
                    "scope_matches": r.scope_matches,
                    "priority_score": r.priority_score,
                    "description": r.skill.description,
                }
                for r in results
            ],
            "contexts": [
                {
                    "skill": c.skill.skill.name,
                    "relevance": c.relevance_score,
                    "tokens_used": c.tokens_used,
                    "chunks": [{"content": ch.result.content[:200]} for ch in c.chunks],
                }
                for c in contexts
            ],
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return

    if not results:
        print(f"No skills matched intent: {intent}")
        return

    print(render_section("Skill Discovery"))
    print(f"  Intent: {intent}")
    print(f"  Agent:  {agent}")
    print(f"  Candidates: {len(results)}")
    print(f"  Used:       {len(contexts)}")
    print()

    for i, r in enumerate(results, 1):
        used_mark = "✓" if any(c.skill.skill.name == r.skill.name for c in contexts) else "—"
        print(f"  [{used_mark}] {i}. {r.skill.name} (score={r.score:.2f})")
        if r.trigger_matches:
            print(f"       triggers: {', '.join(r.trigger_matches)}")
        if r.scope_matches:
            print(f"       scope:    {', '.join(r.scope_matches)}")
        print(f"       priority: {r.skill.priority} (norm={r.priority_score:.2f})")
        print(f"       {r.skill.description}")

    if contexts:
        print()
        print(render_section("Selected Skill Contexts"))
        for c in contexts:
            print(f"\n  --- {c.skill.skill.name} ({c.tokens_used} tokens) ---")
            for ch in c.chunks:
                content = ch.result.content[:300]
                if len(ch.result.content) > 300:
                    content += "..."
                print(f"  {content}")


def cmd_skills_inspect(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    if not raw_args:
        print("Usage: aios skills inspect <name> [--json]", file=sys.stderr)
        sys.exit(1)

    name = raw_args[0]
    as_json = "--json" in raw_args

    registry = SkillRegistry(project_path)
    registry.load()
    skill = registry.get(name)

    if skill is None:
        print(f"Skill not found: {name}")
        sys.exit(1)

    kernel = kernel_factory(project_path)
    kernel.start()
    knowledge = kernel.get_engine("knowledge")

    indexed = False
    chunks_count = 0
    if knowledge is not None:
        sources = knowledge.list_sources("skill")
        for s in sources:
            if s.path and f"/skills/{name}/" in s.path:
                indexed = True
                chunks = getattr(knowledge, "_store", None)
                if chunks is not None:
                    chunks_count = len(chunks.get_source_chunks(s.source_id))
                break

    if as_json:
        print(
            json.dumps(
                {
                    "name": skill.name,
                    "description": skill.description,
                    "triggers": skill.triggers,
                    "scope": skill.scope,
                    "dependencies": skill.dependencies,
                    "priority": skill.priority,
                    "version": skill.version,
                    "owner": skill.owner,
                    "updated_at": skill.updated_at,
                    "status": skill.status,
                    "schema_version": skill.schema_version,
                    "indexed": indexed,
                    "chunks_count": chunks_count,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    print(render_section(f"Skill: {skill.name}"))
    print(render_row("Description", skill.description))
    print(render_row("Status", skill.status))
    print(render_row("Priority", str(skill.priority)))
    print(render_row("Version", skill.version))
    if skill.owner:
        print(render_row("Owner", skill.owner))
    if skill.triggers:
        print(render_row("Triggers", ", ".join(skill.triggers)))
    if skill.scope:
        print(render_row("Scope", ", ".join(skill.scope)))
    if skill.dependencies:
        print(render_row("Dependencies", ", ".join(skill.dependencies)))
    print(render_row("Indexed", "yes" if indexed else "no"))
    if indexed:
        print(render_row("Chunks", str(chunks_count)))


def cmd_skills_stats(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    skill_filter = None
    as_json = False
    date_from = None
    date_to = None

    i = 0
    while i < len(raw_args):
        arg = raw_args[i]
        if arg == "--json":
            as_json = True
        elif arg == "--today":
            from datetime import UTC, datetime

            today = datetime.now(UTC).strftime("%Y-%m-%d")
            date_from = f"{today}T00:00:00"
        elif arg == "--from" and i + 1 < len(raw_args):
            date_from = raw_args[i + 1]
            i += 1
        elif arg == "--to" and i + 1 < len(raw_args):
            date_to = raw_args[i + 1]
            i += 1
        elif arg == "--skill" and i + 1 < len(raw_args):
            skill_filter = raw_args[i + 1]
            i += 1
        elif arg == "--agent" and i + 1 < len(raw_args):
            i += 1  # skip — not implemented in M6
        i += 1

    kernel = kernel_factory(project_path)
    kernel.start()

    telemetry = kernel.get_engine("telemetry")
    if telemetry is None:
        print("Telemetry engine not available.")
        return

    stats = telemetry.query_skill_stats(
        skill=skill_filter,
        date_from=date_from,
        date_to=date_to,
    )

    if as_json:
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        return

    if not stats:
        print("No skill usage records found.")
        return

    print(render_section("Skill Stats"))
    print(
        f"  {'Skill':<20} {'Used':>6} {'Selected':>9} {'Considered':>11} {'AvgScore':>9} {'Tokens':>8}"
    )
    print(f"  {'-' * 20} {'-' * 6} {'-' * 9} {'-' * 11} {'-' * 9} {'-' * 8}")

    for s in stats:
        avg = f"{s['avg_relevance']:.2f}" if s["avg_relevance"] else "—"
        print(
            f"  {s['skill_name']:<20} {s['total_used']:>6} "
            f"{s['total_selected']:>9} {s['total_considered']:>11} "
            f"{avg:>9} {s['total_tokens']:>8}"
        )

    print(f"\n  {len(stats)} skill(s)")
