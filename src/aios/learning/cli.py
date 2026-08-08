"""Learning CLI — read/write for learning candidates.

``aios learning candidates``  list candidates with advisor recommendation
``aios learning approve <id>`` approve a candidate
``aios learning reject <id> --reason "..."``  reject a candidate (reason mandatory)
``aios learning ingest <id>`` ingest an approved candidate into memory
``aios learning export [--format md] [--out PATH]``  materialize approved/ingested
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from aios.core.console import render_section
from aios.learning.models import CandidateState

_CONTENT_PREVIEW_LENGTH = 80


def cmd_learning_candidates(
    raw_args: list[str], project_path: Path, kernel_factory: Callable
) -> None:
    opts = _parse_list_args(raw_args)
    kernel = kernel_factory(project_path)
    kernel.start()

    engine = kernel.get_engine("learning")
    if engine is None:
        print("Learning engine not available.", file=sys.stderr)
        sys.exit(1)

    state: CandidateState | None = opts.get("state")  # type: ignore[assignment]
    limit = opts.get("limit", 100)
    candidates = engine.get_candidates(state=state, limit=limit)

    if opts.get("json"):
        result = []
        for c in candidates:
            rec = c.to_dict()
            adv = engine.get_advisor_recommendation(c.id)
            if adv:
                rec["advisor"] = adv
            reviews = engine.get_reviews(c.id)
            if reviews:
                rec["reviews"] = reviews
            result.append(rec)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if not candidates:
        print("No candidates found.")
        return

    print(render_section("Learning Candidates"))
    for c in candidates:
        rec = engine.get_advisor_recommendation(c.id)
        recommendation = rec["recommendation"] if rec else "?"
        print(
            f"  [{c.id}] [{c.state}] [{c.suggested_type}] "
            f"{c.content[:_CONTENT_PREVIEW_LENGTH]}"
            f"{'...' if len(c.content) > _CONTENT_PREVIEW_LENGTH else ''}"
        )
        print(f"       confidence={c.confidence:.2f} risk={c.risk_level} "
              f"advisor={recommendation}")


def _parse_list_args(raw_args: list[str]) -> dict:
    opts: dict = {"limit": 100}
    i = 0
    while i < len(raw_args):
        arg = raw_args[i]
        if arg == "--json":
            opts["json"] = True
        elif arg == "--state":
            i += 1
            valid = ("draft", "scored", "approved", "rejected", "ingested")
            value = raw_args[i] if i < len(raw_args) else ""
            if value not in valid:
                print(f"--state must be one of {valid}", file=sys.stderr)
                sys.exit(1)
            opts["state"] = value
        elif arg == "--limit":
            i += 1
            opts["limit"] = int(raw_args[i] if i < len(raw_args) else "100")
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}", file=sys.stderr)
            sys.exit(1)
        i += 1
    return opts


def cmd_learning_approve(
    raw_args: list[str], project_path: Path, kernel_factory: Callable
) -> None:
    id_args = [a for a in raw_args if not a.startswith("--")]
    reason = _extract_flag(raw_args, "--reason")

    if not id_args:
        print("Usage: aios learning approve <id> [--reason \"...\"]", file=sys.stderr)
        sys.exit(1)

    candidate_id = int(id_args[0])
    kernel = kernel_factory(project_path)
    kernel.start()

    engine = kernel.get_engine("learning")
    if engine is None:
        print("Learning engine not available.", file=sys.stderr)
        sys.exit(1)

    try:
        engine.approve(candidate_id, reviewer="human", reason=reason)
        print(f"Candidate {candidate_id} approved.")
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_learning_reject(
    raw_args: list[str], project_path: Path, kernel_factory: Callable
) -> None:
    id_args = [a for a in raw_args if not a.startswith("--")]
    reason = _extract_flag(raw_args, "--reason")

    if not id_args:
        print("Usage: aios learning reject <id> --reason \"...\"", file=sys.stderr)
        sys.exit(1)

    if not reason:
        print("Error: --reason is required for reject", file=sys.stderr)
        sys.exit(1)

    candidate_id = int(id_args[0])
    kernel = kernel_factory(project_path)
    kernel.start()

    engine = kernel.get_engine("learning")
    if engine is None:
        print("Learning engine not available.", file=sys.stderr)
        sys.exit(1)

    try:
        engine.reject(candidate_id, reason=reason, reviewer="human")
        print(f"Candidate {candidate_id} rejected.")
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_learning_ingest(
    raw_args: list[str], project_path: Path, kernel_factory: Callable
) -> None:
    id_args = [a for a in raw_args if not a.startswith("--")]

    if not id_args:
        print("Usage: aios learning ingest <id>", file=sys.stderr)
        sys.exit(1)

    candidate_id = int(id_args[0])
    kernel = kernel_factory(project_path)
    kernel.start()

    engine = kernel.get_engine("learning")
    if engine is None:
        print("Learning engine not available.", file=sys.stderr)
        sys.exit(1)

    try:
        version = engine.ingest(candidate_id)
        print(f"Candidate {candidate_id} ingested (version {version}).")
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_learning_export(
    raw_args: list[str], project_path: Path, kernel_factory: Callable
) -> None:
    fmt = _extract_flag(raw_args, "--format") or "md"
    output_path = _extract_flag(raw_args, "--out") or ""

    kernel = kernel_factory(project_path)
    kernel.start()

    engine = kernel.get_engine("learning")
    if engine is None:
        print("Learning engine not available.", file=sys.stderr)
        sys.exit(1)

    approved = engine.get_candidates(state="approved")
    ingested = engine.get_candidates(state="ingested")
    all_candidates = approved + ingested

    if not all_candidates:
        print("No approved or ingested candidates to export.")
        return

    if output_path:
        out_path = Path(output_path)
    else:
        ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        out_path = project_path / ".aios" / "learning" / f"learning-export-{ts}.md"

    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Learning Governance Export",
        f"Generated: {datetime.now(UTC).isoformat()}",
        f"Candidates: {len(all_candidates)} (approved={len(approved)}, ingested={len(ingested)})",
        "",
    ]

    for c in all_candidates:
        lines.append(f"## [{c.id}] [{c.state}] {c.suggested_type}")
        lines.append(f"Confidence: {c.confidence:.2f} | Risk: {c.risk_level}")
        lines.append("")
        lines.append(c.content)
        lines.append("")

    text = "\n".join(lines)
    out_path.write_text(text, encoding="utf-8")
    print(f"Exported {len(all_candidates)} candidates to {out_path}")

    store = engine.get_store()
    if store:
        store.insert_materialization(fmt, str(out_path), len(all_candidates))


def _extract_flag(args: list[str], flag: str) -> str:
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            return args[i + 1]
    return ""


def _cmd_learning(
    raw_args: list[str], project_path: Path, kernel_factory: Callable
) -> None:
    if not raw_args:
        print("Usage: aios learning <subcommand>", file=sys.stderr)
        print()
        print("Subcommands:")
        print("  candidates  List learning candidates")
        print("  approve     Approve a candidate")
        print("  reject      Reject a candidate (--reason required)")
        print("  ingest      Ingest an approved candidate into memory")
        print("  export      Materialize approved/ingested candidates to file")
        return

    sub_map = {
        "candidates": cmd_learning_candidates,
        "approve": cmd_learning_approve,
        "reject": cmd_learning_reject,
        "ingest": cmd_learning_ingest,
        "export": cmd_learning_export,
    }

    sub_name = raw_args[0]
    handler = sub_map.get(sub_name)
    if handler is None:
        print(f"Unknown subcommand: {sub_name}", file=sys.stderr)
        sys.exit(1)

    handler(raw_args[1:], project_path, kernel_factory)
