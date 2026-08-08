"""Knowledge CLI — index, search, and list knowledge sources."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

from aios.core.console import render_row, render_section

_TRUNCATE_LEN = 500


def cmd_knowledge_index(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    kernel = kernel_factory(project_path)
    kernel.start()

    engine = kernel.get_engine("knowledge")
    if engine is None:
        print("Knowledge engine not available.")
        return

    print(render_section("Indexing Knowledge"))
    summary = engine.index()

    print(render_row("Run ID", summary.run_id))
    print(render_row("Sources scanned", str(summary.scanned)))
    print(render_row("Skipped (unchanged)", str(summary.skipped)))
    print(render_row("Reindexed (changed)", str(summary.reindexed)))
    print(render_row("Chunks created", str(summary.chunks_created)))
    print(render_row("Chunks deleted", str(summary.chunks_deleted)))
    print()
    print("Knowledge index complete.")


def cmd_knowledge_search(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    if not raw_args:
        print("Usage: aios knowledge search <query>", file=sys.stderr)
        sys.exit(1)

    query = raw_args[0]
    limit = 20
    as_json = "--json" in raw_args

    kernel = kernel_factory(project_path)
    kernel.start()

    engine = kernel.get_engine("knowledge")
    if engine is None:
        print("Knowledge engine not available.")
        return

    results = engine.search(query, limit=limit)

    if as_json:
        print(json.dumps([r.to_dict() for r in results], indent=2, ensure_ascii=False))
        return

    if not results:
        print(f"No results for: {query}")
        return

    for i, r in enumerate(results, 1):
        source_label = f"{r.source_type}/{r.source_path}"
        print(f"\n--- Result {i} [{source_label}] position {r.position} ---")
        content = r.content[:_TRUNCATE_LEN]
        if len(r.content) > _TRUNCATE_LEN:
            content += "\n... (truncated)"
        print(content)


def cmd_knowledge_sources(
    raw_args: list[str], project_path: Path, kernel_factory: Callable
) -> None:
    type_filter = None
    as_json = False
    for arg in raw_args or []:
        if arg == "--json":
            as_json = True
        elif arg.startswith("--type="):
            type_filter = arg.split("=", 1)[1]
        elif arg == "--type":
            pass

    kernel = kernel_factory(project_path)
    kernel.start()

    engine = kernel.get_engine("knowledge")
    if engine is None:
        print("Knowledge engine not available.")
        return

    sources = engine.list_sources(type_filter)

    if as_json:
        print(json.dumps([s.to_dict() for s in sources], indent=2, ensure_ascii=False))
        return

    if not sources:
        print("No knowledge sources indexed. Run 'aios knowledge index' first.")
        return

    print(render_section("Knowledge Sources"))
    print(f"  {'Type':<16} {'Path':<50} {'Status':<10} {'Hash':<12} Indexed")
    print(f"  {'-' * 16} {'-' * 50} {'-' * 10} {'-' * 12} {'-' * 20}")
    for s in sources:
        hash_short = s.hash[:12] if s.hash else "-"
        indexed = s.indexed_at[:19] if s.indexed_at else "-"
        print(f"  {s.type:<16} {s.path:<50} {s.status:<10} {hash_short:<12} {indexed}")
    print(f"\n  {len(sources)} source(s)")
