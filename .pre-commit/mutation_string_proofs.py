#!/usr/bin/env python3
"""Elevate EQUIVALENT_CANDIDATE string sites into an evidence dossier.

Reads ``mutation-report/evidence.json`` (from ``mutation_evidence``), filters to
``EQUIVALENT_CANDIDATE`` sites, and enriches each with:

* ``context_kind`` -- RAISE / CLI / HELP / LOG / DOCSTRING / OTHER (evidence
  label, not semantic judgment; the agent decides).
* ``source_context`` -- deterministic function body boundary (AST when libcst
  is available, dedent-boundary fallback) with explicit line numbers.
* ``test_locations`` -- sorted list of ``tests/<file>:<line>`` where the
  original literal appears.

Read-only on artifact, source, and tests; deterministic output (sorted by
context_kind, file, func, literal); no edits to code, allowlist, or pragma.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

_RAISE = re.compile(r"\braise\b")
_CLI = re.compile(r"\bclick\.echo\b|\bconsole\.print\b|\btyper\.echo\b|\brich\.print\b")
_HELP = re.compile(r'(?i)^\s*"?usage:|^\s*"\s*--')
_LOG = re.compile(r"\blogger\.\w+\(|\blogging\.\w+\(|\blog\.\w+\(")
_DOC = re.compile(r'"""[^"]*"""|\'\'\'[^\']*\'\'\'|__doc__')


@dataclass
class ProofSite:
    site_id: str
    site: str
    file: str
    func: str
    module: str
    mutant_ids: tuple[str, ...]
    context_kind: str
    literal_original: str | None
    literal_mutated: str | None
    literal_in_tests: bool | None
    test_locations: tuple[dict, ...]
    source_context: dict | None
    source_evidence: dict | None
    exception_type: str | None
    log_level: str | None
    literal_consumers: tuple[str, ...]
    caller_locations: tuple[str, ...]
    catch_locations: tuple[str, ...]
    suggested_disposition: str
    human_disposition: str | None
    human_reason: str | None


def classify_context_kind(orig_line: str) -> str:
    """Label the usage context (evidence, not judgment)."""
    if _RAISE.search(orig_line):
        return "RAISE"
    if _CLI.search(orig_line):
        return "CLI"
    if _HELP.search(orig_line):
        return "HELP"
    if _LOG.search(orig_line):
        return "LOG"
    if _DOC.search(orig_line):
        return "DOCSTRING"
    return "OTHER"


def _extract_function_body(source_text: str, func_name: str) -> tuple[int, int, str] | None:
    """Extract function body via libcst (preferred) or dedent boundary (fallback).

    Returns ``(start_line, end_line, code)`` or ``None`` if not found.
    """
    try:
        return _extract_with_libcst(source_text, func_name)
    except Exception:  # noqa: BLE001
        return _extract_by_dedent(source_text, func_name)


def _extract_with_libcst(source_text: str, func_name: str) -> tuple[int, int, str] | None:
    import libcst as cst  # noqa: PLC0415

    tree = cst.parse_module(source_text)
    for node in tree.children:
        if isinstance(node, (cst.FunctionDef, cst.AsyncFunctionDef)):  # noqa: SIM102
            if node.name.value == func_name:
                lines = source_text.splitlines()
                s, e = node.start_line - 1, node.end_line
                return node.start_line, node.end_line, "\n".join(lines[s:e])
        if isinstance(node, cst.ClassDef):
            for sub in node.body.body:
                if isinstance(sub, (cst.FunctionDef, cst.AsyncFunctionDef)):  # noqa: SIM102
                    if sub.name.value == func_name:
                        lines = source_text.splitlines()
                        return (
                            sub.start_line,
                            sub.end_line,
                            "\n".join(lines[sub.start_line - 1 : sub.end_line]),
                        )
    return None


def _extract_by_dedent(source_text: str, func_name: str) -> tuple[int, int, str] | None:
    lines = source_text.splitlines()
    def_re = re.compile(rf"^\s*(?:async\s+)?def\s+{re.escape(func_name)}\s*\(")
    for i, line in enumerate(lines):
        if def_re.match(line):
            indent = len(line) - len(line.lstrip())
            end = i + 1
            while end < len(lines):
                stripped = lines[end]
                if stripped.strip() == "":
                    break  # blank line = function boundary
                if len(stripped) - len(stripped.lstrip()) > indent:
                    end += 1
                else:
                    break
            return i + 1, end, "\n".join(lines[i:end])
    return None


def _find_test_locations(literal: str, tests_dir: Path) -> list[dict]:
    """Find where literal appears in tests, sorted by (file, line)."""
    results = []
    if not literal or not tests_dir.is_dir():
        return results
    for py in sorted(tests_dir.rglob("*.py")):
        try:
            text = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if literal in line:
                results.append({"file": str(py), "line": i, "snippet": line.strip()[:120]})
    results.sort(key=lambda r: (r["file"], r["line"]))
    return results[:10]


def _find_literal_line(source_text: str, literal: str) -> dict | None:
    """Locate the exact line containing the literal with context before/after."""
    if not literal:
        return None
    lines = source_text.splitlines()
    for i, line in enumerate(lines):
        if literal in line:
            start = max(0, i - 2)
            end = min(len(lines), i + 3)
            return {
                "line": i + 1,
                "code": line.rstrip(),
                "context_before": [lines[j].rstrip() for j in range(start, i)],
                "context_after": [lines[j].rstrip() for j in range(i + 1, end)],
            }
    return None


def _extract_exception_type(line: str) -> str | None:
    """Extract exception class name from a raise statement."""
    m = re.search(r"\braise\s+(\w+(?:Error|Exception))\b", line)
    return m.group(1) if m else None


def _extract_log_level(line: str) -> str | None:
    """Extract log level from logger.debug/info/warning/error call."""
    m = re.search(r"\blogger\.(debug|info|warning|error)\(", line)
    return m.group(1) if m else None


def build_proofs(evidence_path: Path, repo_root: Path, tests_dir: Path) -> list[ProofSite]:  # noqa: PLR0912
    data = json.loads(evidence_path.read_text(encoding="utf-8"))
    sites = [
        s for s in data.get("sites", []) if s.get("suggested_disposition") == "EQUIVALENT_CANDIDATE"
    ]
    proofs: list[ProofSite] = []
    for s in sites:
        orig_lit = s.get("orig_literal")
        mut_lit = None
        if s.get("mutant_ids"):
            mut_lit = f'"{orig_lit}" mutated' if orig_lit else None

        # source context
        src_file = repo_root / s["file"]
        ctx = None
        src_text = None
        if src_file.is_file():
            func_key = s.get("func", "")
            span_key = func_key.rsplit(".", 1)[-1] if "." in func_key else func_key
            parts = span_key.split("\u01c1")  # class ǁ separator
            func_name = (
                parts[-1]
                if len(parts) > 1
                else (span_key[2:] if span_key.startswith("x_") else span_key)
            )
            src_text = src_file.read_text(encoding="utf-8", errors="ignore")
            raw = _extract_function_body(src_text, func_name)
            if raw:
                ctx = {"start_line": raw[0], "end_line": raw[1], "code": raw[2]}

        # context kind: classify the source line that contains the literal
        kind = "OTHER"
        if ctx and ctx["code"] and orig_lit:
            for cline in ctx["code"].splitlines():
                if orig_lit in cline:
                    kind = classify_context_kind(cline)
                    break
        elif ctx and ctx["code"]:
            kind = classify_context_kind(ctx["code"])

        # source evidence: exact line where literal appears + context
        src_evidence = None
        exc_type = None
        log_lvl = None
        if src_text and orig_lit:
            src_evidence = _find_literal_line(src_text, orig_lit)
            if src_evidence:
                exc_type = _extract_exception_type(src_evidence["code"])
                log_lvl = _extract_log_level(src_evidence["code"])

        # test locations
        test_locs = _find_test_locations(orig_lit, tests_dir) if orig_lit else []
        lit_in_tests = len(test_locs) > 0

        # site string
        site_str = (
            f"{s['file']}::{s['func']}::{orig_lit}" if orig_lit else f"{s['file']}::{s['func']}"
        )

        proofs.append(
            ProofSite(
                site_id=s["site_id"],
                site=site_str,
                file=s["file"],
                func=s["func"],
                module=s.get("module", ""),
                mutant_ids=tuple(s.get("mutant_ids", [])),
                context_kind=kind,
                literal_original=orig_lit,
                literal_mutated=mut_lit,
                literal_in_tests=lit_in_tests,
                test_locations=tuple(test_locs),
                source_context=ctx,
                source_evidence=src_evidence,
                exception_type=exc_type,
                log_level=log_lvl,
                literal_consumers=(),
                caller_locations=(),
                catch_locations=(),
                suggested_disposition="EQUIVALENT_CANDIDATE",
                human_disposition=None,
                human_reason=None,
            )
        )
    return sorted(proofs, key=lambda p: (p.context_kind, p.file, p.func, p.literal_original or ""))


def render_md(proofs: list[ProofSite]) -> str:
    lines = [
        "# String Mutation Evidence Proofs",
        "",
        "Each site is an **EQUIVALENT_CANDIDATE**: the mutation changes a literal",
        "but the agent must determine whether that change is observable through",
        "a contract-protected behavior. Evidence only; the agent decides.",
        f"Total sites: {len(proofs)}",
        "",
    ]
    by_kind: dict[str, list[ProofSite]] = {}
    for p in proofs:
        by_kind.setdefault(p.context_kind, []).append(p)
    for kind in ["LOG", "RAISE", "CLI", "HELP", "DOCSTRING", "OTHER"]:
        group = by_kind.get(kind, [])
        if not group:
            continue
        lines.append(f"## {kind} ({len(group)})")
        for p in group:
            lines.append(f"### {p.site_id}")
            lines.append(f"- **site**: `{p.site}`")
            lines.append(f"- **mutants**: `{list(p.mutant_ids)}`")
            lines.append(f"- **literal_original**: `{p.literal_original}`")
            lines.append(f"- **literal_in_tests**: {p.literal_in_tests}")
            if p.test_locations:
                lines.append("- **test_locations**:")
                for loc in p.test_locations:
                    lines.append(f"  - {loc['file']}:{loc['line']}")
            if p.source_context:
                sc = p.source_context
                lines.append(f"- **source_context** [{sc['start_line']}-{sc['end_line']}]:")
                lines.append("  ```")
                for cline in sc["code"].splitlines()[:30]:
                    lines.append(f"  {cline}")
                lines.append("  ```")
            if p.source_evidence:
                se = p.source_evidence
                lines.append(f"- **source_evidence** [linha {se['line']}]:")
                for bl in se["context_before"]:
                    lines.append(f"    {bl}")
                lines.append(f"  >> {se['code']}")
                for al in se["context_after"]:
                    lines.append(f"    {al}")
            if p.exception_type:
                lines.append(f"- **exception_type**: {p.exception_type}")
            if p.log_level:
                lines.append(f"- **log_level**: {p.log_level}")
            lines.append("- **human_disposition**: (DECIDED/DEFERRED/BLOCKED)")
            lines.append("- **human_reason**: (preencher)")
            lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--evidence", default="mutation-report/evidence.json", type=Path)
    ap.add_argument("--repo-root", default=".", type=Path)
    ap.add_argument("--tests-dir", default="tests", type=Path)
    ap.add_argument("--out", default="mutation-report", type=Path)
    args = ap.parse_args(argv)

    if not args.evidence.is_file():
        print(f"ERROR: {args.evidence} not found (run mutation_evidence first)", file=sys.stderr)
        return 2

    proofs = build_proofs(args.evidence, args.repo_root, args.tests_dir)
    payload = {
        "meta": {"schema_version": 1, "source": str(args.evidence), "total": len(proofs)},
        "summary": {
            "by_context_kind": {
                k: len(v) for k, v in _group(proofs, lambda p: p.context_kind).items()
            },
            "literal_in_tests": sum(1 for p in proofs if p.literal_in_tests),
            "literal_not_in_tests": sum(1 for p in proofs if p.literal_in_tests is False),
        },
        "proofs": [asdict(p) for p in proofs],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "evidence-string-proofs.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    (args.out / "evidence-string-proofs.md").write_text(render_md(proofs), encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))
    print(f"\nwrote {args.out}/evidence-string-proofs.{{json,md}} ({len(proofs)} sites)")
    return 0


def _group(items, key):
    d: dict[str, list] = {}
    for item in items:
        d.setdefault(key(item), []).append(item)
    return dict(sorted(d.items()))


if __name__ == "__main__":
    sys.exit(main())
