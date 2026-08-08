"""Knowledge CLI — index, search, and list knowledge sources."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path

from aios.core.console import render_row, render_section

_TRUNCATE_LEN = 500


def cmd_knowledge_index(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    do_embed = "--embed" in (raw_args or [])
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

    if do_embed:
        embed_result = engine.embed_indexed()
        status = embed_result.get("status", "ok")
        print(
            render_row(
                "Embeddings",
                f"{embed_result.get('embedded', 0)} embedded, "
                f"{embed_result.get('skipped', 0)} skipped ({status})",
            )
        )

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


def cmd_knowledge_retrieve(
    raw_args: list[str], project_path: Path, kernel_factory: Callable
) -> None:
    if not raw_args:
        usage = "Usage: aios knowledge retrieve <query> [--agent X] [--vector] [--json]"
        print(usage, file=sys.stderr)
        sys.exit(1)

    query = raw_args[0]
    agent = "research"
    use_vector = False
    as_json = False
    limit = 20

    for arg in raw_args:
        if arg == "--json":
            as_json = True
        elif arg == "--vector":
            use_vector = True
        elif arg == "--agent":
            idx = raw_args.index(arg) + 1
            if idx < len(raw_args) and not raw_args[idx].startswith("-"):
                agent = raw_args[idx]

    kernel = kernel_factory(project_path)
    kernel.start()

    engine = kernel.get_engine("knowledge")
    if engine is None:
        print("Knowledge engine not available.")
        return

    result = engine.retrieve(query, agent=agent, limit=limit, use_vector=use_vector)

    telemetry = kernel.get_engine("telemetry")
    if telemetry is not None:
        telemetry.record_retrieval(
            {
                "agent": agent,
                "query": query,
                "chunks_retrieved": result.chunks_retrieved,
                "chunks_selected": result.chunks_selected,
                "tokens_before": result.tokens_before,
                "tokens_after": result.tokens_after,
                "compression_ratio": result.compression_ratio,
                "retrieval_latency_ms": result.retrieval_latency_ms,
                "retriever": "vector" if use_vector else "keyword",
            }
        )

    if as_json:
        output = {
            "agent": agent,
            "selected_count": result.selected_count,
            "chunks_retrieved": result.chunks_retrieved,
            "chunks_selected": result.chunks_selected,
            "tokens_before": result.tokens_before,
            "tokens_after": result.tokens_after,
            "compression_ratio": result.compression_ratio,
            "retrieval_latency_ms": result.retrieval_latency_ms,
            "prompt_context": result.prompt_context,
            "chunks": [
                {
                    "score": c.score,
                    "justification": c.justification,
                    "content": c.result.content,
                    "source": f"{c.result.source_type}/{c.result.source_path}",
                    "token_estimate": c.result.token_estimate,
                }
                for c in result.chunks
            ],
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return

    if not result.chunks:
        print(f"No relevant knowledge for: {query}")
        return

    print(render_section("Retrieval Results"))
    print(render_row("Agent", agent))
    print(render_row("Retrieved", str(result.chunks_retrieved)))
    print(render_row("Selected", str(result.chunks_selected)))
    print(render_row("Tokens before", str(result.tokens_before)))
    print(render_row("Tokens after", str(result.tokens_after)))
    print(render_row("Compression", f"{result.compression_ratio:.1%}"))
    print(render_row("Latency", f"{result.retrieval_latency_ms:.1f}ms"))

    print(f"\n--- Prompt Context (agent={agent}) ---")
    print(result.prompt_context)


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
