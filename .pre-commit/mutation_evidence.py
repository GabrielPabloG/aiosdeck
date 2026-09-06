#!/usr/bin/env python3
"""Epistemic-triage evidence harness: turn survivor *sites* into a decision log.

The triage report tells us survivors cluster into different phenomena (string
vs arg-removal vs operator). This tool surfaces the *evidence* a human needs to
apply the contract criterion -- "the mutation changes a value but no
contract-protected observable behavior" -- so equivalence is PROVEN, never
assumed. It only *suggests* a disposition; it never edits source, tests, the
allowlist, or adds pragmas.

Read-only on the artifact; deterministic (stable ids, sorted output, no clock).

    EvidenceSite = one (file, func, category, changed-line) collapsed over the
    mutants that share it, with: usage context, the mutated literal, whether the
    literal/function appear in the test suite, and a suggested disposition.

Dispositions mirror E2.6 ("unknowns must not disappear quietly"):
    EQUIVALENT_CANDIDATE  likely non-contractual -> human proves -> `# pragma`
    CONTRACT_TEST         observable behavior, weak/absent assertion -> add test
    COVERAGE_GAP          no test exercises the function at all -> add test
    NEEDS_REVIEW          cannot classify without a product decision
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mutation_classifier import (  # noqa: E402
    STRING_MUTATION,
    UNKNOWN,
    HybridClassifier,
    changed_line_pair,
)
from mutation_triage import _load_json, _read, _slice, build_records, split_mutant_key  # noqa: E402

SCHEMA_VERSION = 1

EQUIVALENT_CANDIDATE = "EQUIVALENT_CANDIDATE"
CONTRACT_TEST = "CONTRACT_TEST"
COVERAGE_GAP = "COVERAGE_GAP"
NEEDS_REVIEW = "NEEDS_REVIEW"

_MSG = re.compile(
    r"\braise\b|Error\(|Exception\(|warning|logger|\.info\(|\.debug\(|\.error\(|print\("
)
_CMP = re.compile(
    r"==|!=|\bin\b|startswith|endswith|\bsplit\b|\bjoin\b|\bformat\b|re\.(match|search|compile)|\.get\("
)
_KEY = re.compile(r"['\"][^'\"]+['\"]\s*:")
_SQL = re.compile(r"\bSELECT\b|\bWHERE\b|\bINSERT\b|\bUPDATE\b|\bDELETE\b", re.I)
_PATH = re.compile(r"open\(|Path\(|os\.path|\.json|\.md|\.py\b|https?://|/api/|--")
_CALL = re.compile(r"\w+\([^)]*['\"]")
_LITERAL = re.compile(r"(['\"])(.*?)\1")


def string_context(line: str) -> str:  # noqa: PLR0911 - one guard per usage context
    """Usage context of a mutated string literal (drives the equivalence call)."""
    if _MSG.search(line):
        return "MESSAGE"
    if _CMP.search(line):
        return "COMPARED"
    if _KEY.search(line):
        return "DICT_KEY"
    if _SQL.search(line):
        return "SQL"
    if _PATH.search(line):
        return "PATH"
    if _CALL.search(line):
        return "CALL_ARG"
    return "OTHER"


def literal_of(line: str) -> str | None:
    """First string literal's content on the line, or None."""
    m = _LITERAL.search(line)
    return m.group(2) if m else None


def suggest_disposition(  # noqa: PLR0911 - one guard per disposition case
    category: str, context: str, in_tests: bool | None, func_has_test: bool
) -> str:
    """First-pass disposition SUGGESTION. A human confirms before any exclusion."""
    if category == UNKNOWN:
        return NEEDS_REVIEW
    if category == STRING_MUTATION:
        if context == "MESSAGE":
            return NEEDS_REVIEW if in_tests else EQUIVALENT_CANDIDATE
        if context in ("COMPARED", "DICT_KEY"):
            return CONTRACT_TEST
        if context == "SQL":
            return CONTRACT_TEST if in_tests else COVERAGE_GAP
        return NEEDS_REVIEW  # CALL_ARG / PATH / OTHER
    return CONTRACT_TEST if func_has_test else COVERAGE_GAP


@dataclass(frozen=True)
class EvidenceSite:
    site_id: str
    file: str
    module: str
    func: str
    category: str
    status: str
    context: str
    orig_literal: str | None
    literal_in_tests: bool | None
    func_has_test: bool
    suggested_disposition: str
    mutant_ids: tuple[str, ...] = field(default_factory=tuple)


def _site_id(file: str, func: str, category: str, line: str) -> str:
    raw = f"{file}|{func}|{category}|{line}".encode()
    return hashlib.sha1(raw).hexdigest()[:12]  # noqa: S324 - stable grouping key, not security


def build_sites(mutants_dir: Path, tests_blob: str, tests_by_func: dict) -> list[EvidenceSite]:
    """Collapse classified survivor records into evidence sites (one per change)."""
    records = build_records(mutants_dir, set(), HybridClassifier())
    cache: dict[str, tuple[list[str], dict]] = {}
    groups: dict[tuple, dict] = {}
    for r in records:
        if r.allowlisted or r.status == "timeout":
            continue
        if r.file not in cache:
            spans = _load_json(mutants_dir / f"{r.file}.spans") or {}
            gen = _read(mutants_dir / r.file)
            cache[r.file] = (gen.splitlines() if gen else [], spans.get("spans", {}))
        gen_lines, spans = cache[r.file]
        parsed = split_mutant_key(r.mutant_id)
        if not parsed:
            continue
        _module, span_key, n = parsed
        orig = _slice(gen_lines, spans.get(f"{span_key}__mutmut_orig", [])) or ""
        mut = _slice(gen_lines, spans.get(f"{span_key}__mutmut_{n}", [])) or ""
        pair = changed_line_pair(orig, mut) or ("", "")
        key = (r.file, r.func, r.category, pair[0])
        g = groups.setdefault(
            key, {"status": r.status, "module": r.module, "lines": pair, "ids": []}
        )
        g["ids"].append(r.mutant_id)

    sites: list[EvidenceSite] = []
    for (file, func, category, o_line), g in groups.items():
        context = string_context(o_line) if category == STRING_MUTATION else "n/a"
        lit = literal_of(o_line) if category == STRING_MUTATION else None
        in_tests = (lit in tests_blob) if lit else None
        func_has_test = bool(tests_by_func.get(func))
        disp = suggest_disposition(category, context, in_tests, func_has_test)
        sites.append(
            EvidenceSite(
                _site_id(file, func, category, o_line),
                file,
                g["module"],
                func,
                category,
                g["status"],
                context,
                lit,
                in_tests,
                func_has_test,
                disp,
                tuple(sorted(g["ids"])),
            )
        )
    return sorted(sites, key=lambda s: (s.suggested_disposition, s.file, s.func, s.site_id))


def summarize(sites: list[EvidenceSite]) -> dict:
    return {
        "by_disposition": dict(sorted(Counter(s.suggested_disposition for s in sites).items())),
        "by_category": dict(sorted(Counter(s.category for s in sites).items())),
        "string_by_context": dict(
            sorted(Counter(s.context for s in sites if s.category == STRING_MUTATION).items())
        ),
        "sites": len(sites),
    }


def render_log_md(sites: list[EvidenceSite]) -> str:
    lines = [
        "# Mutation Triage Log",
        "",
        "Confirm each site's `disposition` (DECIDED/DEFERRED/BLOCKED).",
        "Suggested dispositions are hints, not proof. Only proven EQUIVALENT_CANDIDATE",
        "sites may receive `# pragma: no mutate`.",
        "",
    ]
    order = [EQUIVALENT_CANDIDATE, CONTRACT_TEST, COVERAGE_GAP, NEEDS_REVIEW]
    by_disp: dict[str, list[EvidenceSite]] = defaultdict(list)
    for s in sites:
        by_disp[s.suggested_disposition].append(s)
    for disp in order:
        group = by_disp.get(disp, [])
        lines.append(f"## {disp} ({len(group)})")
        for s in group:
            lit = f' "{s.orig_literal}"' if s.orig_literal else ""
            flag = (
                ""
                if s.literal_in_tests is None
                else (" [in-tests]" if s.literal_in_tests else " [not-in-tests]")
            )
            lines.append(
                f"- [ ] `{s.site_id}` {s.file}::{s.func} :: {s.category}"
                f"{'/' + s.context if s.context != 'n/a' else ''}{lit}{flag}"
                f" ({len(s.mutant_ids)} mutant) -> disposition:"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mutants-dir", default="mutants", type=Path)
    ap.add_argument("--out", default="mutation-report", type=Path)
    ap.add_argument("--tests-dir", default="tests", type=Path)
    args = ap.parse_args(argv)

    mdir: Path = args.mutants_dir
    if not (mdir / "src").is_dir():
        print(f"ERROR: {mdir}/src not found (raw mutmut artifact required)", file=sys.stderr)
        return 2
    stats = _load_json(mdir / "mutmut-stats.json")
    tests_by_func = (
        stats.get("tests_by_mangled_function_name", {}) if isinstance(stats, dict) else {}
    )
    tests_blob = (
        "\n".join(
            p.read_text(encoding="utf-8", errors="ignore")
            for p in sorted(args.tests_dir.rglob("*.py"))
        )
        if args.tests_dir.is_dir()
        else ""
    )

    sites = build_sites(mdir, tests_blob, tests_by_func)
    summary = summarize(sites)
    payload = {
        "meta": {"schema_version": SCHEMA_VERSION, "mutants_dir": str(mdir)},
        "summary": summary,
        "sites": [asdict(s) for s in sites],
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "evidence.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.out / "triage-log.md").write_text(render_log_md(sites), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print(f"\nwrote {args.out}/evidence.json + triage-log.md ({len(sites)} sites)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
