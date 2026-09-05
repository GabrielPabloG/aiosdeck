#!/usr/bin/env python3
"""Mutation triage: turn raw mutmut survivors into an actionable, deterministic map.

Answers "which files and which *kinds* of change are my tests letting through?"
instead of a single global score. Reads a mutmut artifact (``.meta`` + ``.spans``
+ generated sources + ``mutmut-cicd-stats.json``) and writes a report elsewhere.

Hard guarantees (both unit-tested):
  * READ-ONLY on the artifact -- never writes under ``--mutants-dir``; mutmut's
    results are never mutated by classification.
  * DETERMINISTIC -- identical artifact yields byte-identical ``.json``/``.md``:
    total orderings, relative paths, no clock in the report core.
  * NOTHING SILENTLY DROPPED -- every mutant is counted; ``UNKNOWN`` is an
    explicit bucket; observed per-status counts must reconcile with the stats
    json (else ``reconciliation.ok`` is false).

Analysis only: it writes no tests and never edits the equivalents allowlist.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mutation_classifier import UNKNOWN, HybridClassifier  # noqa: E402

SCHEMA_VERSION = 1
_SPAN_LEN = 2  # a span is [start, end]
_MUTIDX = re.compile(r"__mutmut_(\d+)$")

# exit_code -> status (mirrors mutmut 3.7 status_by_exit_code; verified against
# the artifact so per-status counts reconcile exactly with the stats json).
_STATUS = {
    0: "survived",
    1: "killed",
    3: "killed",
    37: "killed",
    5: "no tests",
    33: "no tests",
    24: "timeout",
    -24: "timeout",
    36: "timeout",
    152: "timeout",
    255: "timeout",
    35: "suspicious",
    34: "skipped",
    2: "interrupted",
}
CLASSIFIED = ("survived", "no tests", "timeout")  # statuses we recover a mutator for


def status_for(code: int | None) -> str:
    if code is None:
        return "not checked"
    return _STATUS.get(code, "suspicious")


def split_mutant_key(key: str) -> tuple[str, str, str] | None:
    """``<module>.<span_key>__mutmut_<N>`` -> ``(module, span_key, N)`` or None."""
    m = _MUTIDX.search(key)
    if not m or "." not in key:
        return None
    module, span_key = key[: m.start()].rsplit(".", 1)
    return module, span_key, m.group(1)


@dataclass(frozen=True)
class MutationRecord:
    """One mutant and its recovered mutator category."""

    mutant_id: str
    module: str
    file: str
    func: str
    line: int | None
    status: str
    category: str
    confidence: float
    classifier: str
    allowlisted: bool


def _slice(lines: list[str], span: list[int]) -> str | None:
    if not isinstance(span, list) or len(span) != _SPAN_LEN:
        return None
    start, end = span
    if start < 1 or end < start or end > len(lines):
        return None
    return "\n".join(lines[start - 1 : end])


def _load_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def build_records(
    mutants_dir: Path, allowlist: set[str], classifier: HybridClassifier
) -> list[MutationRecord]:
    """Read every ``*.meta`` under ``mutants_dir/src`` and classify its mutants."""
    records: list[MutationRecord] = []
    for meta_path in sorted((mutants_dir / "src").rglob("*.meta")):
        rel = meta_path.relative_to(mutants_dir).with_suffix("")  # src/.../engine.py
        spans_data = _load_json(mutants_dir / f"{rel}.spans")
        gen_text = _read(mutants_dir / rel)
        meta = _load_json(meta_path)
        if not isinstance(meta, dict) or not isinstance(spans_data, dict):
            continue
        spans = spans_data.get("spans", {})
        gen_lines = gen_text.splitlines() if gen_text else []
        for key, code in sorted(meta.get("exit_code_by_key", {}).items()):
            status = status_for(code)
            if status not in CLASSIFIED:
                continue
            parsed = split_mutant_key(key)
            if not parsed:
                records.append(_unknown_record(key, str(rel), status, allowlist))
                continue
            module, span_key, n = parsed
            category, conf, method, line = "n/a", 0.0, "none", None
            if gen_lines:
                orig = _slice(gen_lines, spans.get(f"{span_key}__mutmut_orig", []))
                mut = _slice(gen_lines, spans.get(f"{span_key}__mutmut_{n}", []))
                if orig is not None and mut is not None:
                    cl = classifier.classify(orig, mut)
                    category, conf, method = cl.category, round(cl.confidence, 2), cl.method
            records.append(
                MutationRecord(
                    key,
                    module,
                    str(rel),
                    f"{module}.{span_key}",
                    line,
                    status,
                    category,
                    conf,
                    method,
                    key in allowlist,
                )
            )
    return records


def _unknown_record(key: str, file: str, status: str, allowlist: set[str]) -> MutationRecord:
    return MutationRecord(
        key, "", file, key, None, status, UNKNOWN, 0.0, "unknown", key in allowlist
    )


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


# --------------------------------------------------------------------------- #
# aggregation + reconciliation
# --------------------------------------------------------------------------- #
def reconcile(records: list[MutationRecord], stats: dict) -> dict:
    observed = Counter(r.status for r in records)
    expected = {
        "survived": stats.get("survived", 0),
        "no tests": stats.get("no_tests", 0),
        "timeout": stats.get("timeout", 0),
    }
    checks = {k: {"expected": v, "observed": observed.get(k, 0)} for k, v in expected.items()}
    return {"ok": all(c["expected"] == c["observed"] for c in checks.values()), "checks": checks}


def aggregate(records: list[MutationRecord], top: int) -> dict:
    surv = [r for r in records if r.status == "survived"]
    killable = [r for r in surv if not r.allowlisted]
    by_file: Counter[str] = Counter(r.file for r in killable)
    by_category: Counter[str] = Counter(r.category for r in killable)
    by_file_cat: dict[str, Counter[str]] = defaultdict(Counter)
    for r in killable:
        by_file_cat[r.file][r.category] += 1
    no_tests_by_file: Counter[str] = Counter(r.file for r in records if r.status == "no tests")
    return {
        "by_status": {k: v for k, v in sorted(Counter(r.status for r in records).items())},
        "allowlisted_survivors": len(surv) - len(killable),
        "by_category": _rank(by_category),
        "by_file": _rank(by_file, top),
        "no_tests_by_file": _rank(no_tests_by_file, top),
        "by_file_category": {f: _rank(by_file_cat[f]) for f, _ in _rank(by_file, top)},
    }


def _rank(counter: Counter[str], limit: int = 0) -> list[list]:
    ordered = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    if limit:
        ordered = ordered[:limit]
    return [[k, v] for k, v in ordered]


# --------------------------------------------------------------------------- #
# rendering (deterministic)
# --------------------------------------------------------------------------- #
def render_md(meta: dict, recon: dict, agg: dict, top: int) -> str:
    lines = ["# Mutation Report", "", "```"]
    lines.append(f"status_counts={agg['by_status']}")
    lines.append(f"allowlisted_equivalents(survivors)={agg['allowlisted_survivors']}")
    lines.append(f"reconciliation_ok={recon['ok']}")
    lines.append("```")
    if not recon["ok"]:
        lines += ["", f"**RECONCILIATION FAILED**: {recon['checks']}"]
    lines += ["", "## Survivors by category (killable)"]
    for cat, n in agg["by_category"]:
        lines.append(f"- {cat}: {n}")
    lines += ["", f"## Survivors by file (top {top})"]
    for f, n in agg["by_file"]:
        lines.append(f"- {n:>5}  {f}")
    lines += ["", f"## File \u00d7 category (top {top} files)"]
    for f, cats in agg["by_file_category"].items():
        lines.append(f"\n### {f}")
        for cat, n in cats:
            lines.append(f"  - {cat}: {n}")
    lines += ["", f"## No-tests by file (top {top})"]
    for f, n in agg["no_tests_by_file"]:
        lines.append(f"- {n:>5}  {f}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mutants-dir", default="mutants", type=Path)
    ap.add_argument(
        "--stats", default=None, type=Path, help="default: <mutants-dir>/mutmut-cicd-stats.json"
    )
    ap.add_argument("--allowlist", default=".github/mutmut-equivalents.txt", type=Path)
    ap.add_argument("--out", default="mutation-report", type=Path)
    ap.add_argument("--top", default=20, type=int)
    ap.add_argument("--min-confidence", default=0.8, type=float)
    ap.add_argument("--strict", action="store_true", help="exit non-zero if reconciliation fails")
    args = ap.parse_args(argv)

    mdir: Path = args.mutants_dir
    if not (mdir / "src").is_dir():
        print(f"ERROR: {mdir}/src not found (raw mutmut artifact required)", file=sys.stderr)
        return 2
    stats_path = args.stats or (mdir / "mutmut-cicd-stats.json")
    stats = _load_json(stats_path)
    if not isinstance(stats, dict):
        print(f"ERROR: cannot read stats at {stats_path}", file=sys.stderr)
        return 2

    allow_text = (
        _read(args.allowlist) if args.allowlist.is_absolute() else _read(Path(args.allowlist))
    )
    allowlist = {ln.split("#", 1)[0].strip() for ln in (allow_text or "").splitlines()}
    allowlist = {a for a in allowlist if a}

    records = build_records(mdir, allowlist, HybridClassifier(min_confidence=args.min_confidence))
    recon = reconcile(records, stats)
    agg = aggregate(records, args.top)
    meta = {
        "schema_version": SCHEMA_VERSION,
        "mutants_dir": str(mdir),
        "top": args.top,
        "min_confidence": args.min_confidence,
    }

    args.out.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": meta,
        "reconciliation": recon,
        "aggregates": agg,
        "records": sorted((asdict(r) for r in records), key=lambda d: d["mutant_id"]),
    }
    (args.out / "mutation-triage.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.out / "mutation-triage.md").write_text(
        render_md(meta, recon, agg, args.top), encoding="utf-8"
    )

    print(render_md(meta, recon, agg, args.top))
    print(f"\nwrote {args.out}/mutation-triage.{{json,md}}  ({len(records)} classified records)")
    if not recon["ok"] and args.strict:
        print("FAIL: reconciliation mismatch (incomplete/corrupt artifact?)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
