#!/usr/bin/env python3
"""Mutation-gate helper: classify survivors as introduced vs legacy.

Deterministic, artifact-based location of each surviving mutant's source
line, so the PR-scoped mutation gate judges only the code a PR actually
touched and treats everything else as pre-existing debt.

Pipeline (per survivor, from ``mutmut results``):

    name = "<module>.<span_key>__mutmut_<N>"
      -> span_key / N
      -> module -> source path  (src/<module-as-dirs>.py)
      -> mutants/<path>.spans   (__mutmut_orig and __mutmut_N line ranges,
                                 which index into the *generated* file)
      -> diff the two function copies in mutants/<path> to find the mutated
         line, anchored on the ``def`` line so the rename and any leading
         blank/comment lines do not shift it
      -> real line = FunctionDef.lineno + (mutated_rel - def_index)
      -> introduced iff that line is in the merge-base diff's added lines

Fail-closed: any ambiguity (unresolved module/file, missing span, no ``def``
line, function absent in the AST, multiple disjoint changed blocks, unreadable
file) yields ``None`` and the survivor is counted as INTRODUCED. A survivor is
never demoted to LEGACY just because its location could not be determined.

The pure functions take text arguments (no I/O) so they are unit-testable
without mutmut; only ``main`` shells out to git / mutmut.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import json
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

CLASS_SEP = "\u01c1"  # mutmut's mangled class/method separator (LATIN CAPITAL LETTER DZ)
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
SURVIVOR_RE = re.compile(r"^(?P<full>.+)__mutmut_(?P<n>\d+)$")
DEF_PREFIXES = ("def ", "async def ")
_METHOD_PARTS = 3  # span_key split on CLASS_SEP yields x ǁ Class ǁ method
_SPAN_LEN = 2  # a span is [start, end]

# A "survived" mutant goes through the introduced/legacy gate. The others are
# always fatal (independent of source location), preserving the original CI
# hard-fail semantics: a timeout/suspicious/segfault/no-tests mutant blocks the
# PR even on a legacy line, because it signals infrastructure/coverage failure,
# not merely an untested line.
SURVIVED = "survived"
FATAL_STATUSES = frozenset({"suspicious", "timeout", "segfault", "no tests"})
BAD_STATUSES = frozenset({SURVIVED}) | FATAL_STATUSES


# --------------------------------------------------------------------------- #
# Parsing: git diff, mutmut results, allowlist, survivor name
# --------------------------------------------------------------------------- #
def parse_changed_lines(diff_text: str) -> dict[str, set[int]]:
    """Map each ``+++ b/<path>`` file to the set of added line numbers.

    Handles multiple hunks per file, ``+c,d`` (d added lines from c), a bare
    ``+c`` (one line), and ``+c,0`` (pure deletion / insertion point -> no
    added lines).
    """
    changed: dict[str, set[int]] = {}
    current: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current = line[len("+++ b/") :].strip()
            changed.setdefault(current, set())
            continue
        if line.startswith("+++ "):  # /dev/null or a rename target we ignore
            current = None
            continue
        if line.startswith("@@") and current is not None:
            m = HUNK_RE.match(line)
            if not m:
                continue
            start = int(m.group(1))
            count = int(m.group(2)) if m.group(2) is not None else 1
            for offset in range(count):
                changed[current].add(start + offset)
    return changed


def parse_results(results_text: str) -> list[tuple[str, str]]:
    """Extract ``(name, status)`` for every not-killed mutant from ``mutmut results``."""
    out: list[tuple[str, str]] = []
    for raw in results_text.splitlines():
        line = raw.strip()
        if ": " not in line:
            continue
        name, status = line.rsplit(": ", 1)
        if status.strip() in BAD_STATUSES:
            out.append((name.strip(), status.strip()))
    return out


def load_allowlist(text: str) -> set[str]:
    """Read the equivalents allowlist: ``<name>  # reason`` lines, ignoring comments."""
    allowed: set[str] = set()
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            allowed.add(line)
    return allowed


def split_survivor_name(name: str) -> tuple[str, str, str] | None:
    """Split ``<module>.<span_key>__mutmut_<N>`` into ``(module, span_key, N)``."""
    m = SURVIVOR_RE.match(name)
    if not m:
        return None
    full = m.group("full")
    if "." not in full:
        return None
    module, span_key = full.rsplit(".", 1)
    return module, span_key, m.group("n")


def span_key_to_class_func(span_key: str) -> tuple[str | None, str] | None:
    """Return ``(class_name, func_name)`` from a mangled span_key, or None."""
    if CLASS_SEP in span_key:
        parts = span_key.split(CLASS_SEP)  # x ǁ Class ǁ method [ǁ ...]
        if len(parts) < _METHOD_PARTS:
            return None
        return parts[1], parts[-1]
    if span_key.startswith("x_"):
        return None, span_key[len("x_") :]
    return None


def module_to_path(module: str, source_root: str) -> str:
    return f"{source_root}/{module.replace('.', '/')}.py"


# --------------------------------------------------------------------------- #
# AST + generated-file location
# --------------------------------------------------------------------------- #
def func_def_line(source_text: str, class_name: str | None, func_name: str) -> int | None:
    """Line of the ``def`` for a module function or class method; None if ambiguous."""
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return None
    matches: list[int] = []
    if class_name is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for sub in node.body:
                    is_fn = isinstance(sub, ast.FunctionDef | ast.AsyncFunctionDef)
                    if is_fn and sub.name == func_name:
                        matches.append(sub.lineno)
    else:
        for node in tree.body:
            is_fn = isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            if is_fn and node.name == func_name:
                matches.append(node.lineno)
    if len(matches) != 1:
        return None
    return matches[0]


def def_index(copy_lines: list[str]) -> int | None:
    for i, line in enumerate(copy_lines):
        stripped = line.lstrip()
        if stripped.startswith(DEF_PREFIXES):
            return i
    return None


def mutated_rel_index(orig: list[str], mut: list[str]) -> int | None:
    """First changed line (in ``orig`` coords) excluding the ``def`` rename line.

    Returns None when there is no real mutation, or when the changes are not a
    single contiguous block (ambiguous -> caller fails closed).
    """
    di = def_index(orig)
    if di is None:
        return None
    sm = difflib.SequenceMatcher(a=orig, b=mut, autojunk=False)
    changed: set[int] = set()
    for tag, i1, i2, _j1, _j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag in ("replace", "delete"):
            changed.update(range(i1, i2))
        elif tag == "insert":
            changed.add(i1)  # anchor at the insertion point
    changed.discard(di)  # the def line always differs due to the rename
    if not changed:
        return None
    lo, hi = min(changed), max(changed)
    if set(range(lo, hi + 1)) != changed:  # non-contiguous blocks -> ambiguous
        return None
    return lo


def _slice_span(gen_lines: list[str], span: list[int]) -> list[str] | None:
    if not isinstance(span, list) or len(span) != _SPAN_LEN:
        return None
    start, end = span
    if start < 1 or end < start or end > len(gen_lines):
        return None
    return gen_lines[start - 1 : end]


def resolve_survivor_line(  # noqa: PLR0911 - fail-closed guard clauses, one per failure mode
    name: str,
    spans: Mapping[str, list[int]],
    generated_text: str,
    source_text: str,
) -> int | None:
    """Absolute source line mutated by ``name``, or None (fail-closed)."""
    parsed = split_survivor_name(name)
    if not parsed:
        return None
    _module, span_key, n = parsed
    cf = span_key_to_class_func(span_key)
    if not cf:
        return None
    class_name, func_name = cf
    base_line = func_def_line(source_text, class_name, func_name)
    if base_line is None:
        return None
    orig_key = f"{span_key}__mutmut_orig"
    mut_key = f"{span_key}__mutmut_{n}"
    if orig_key not in spans or mut_key not in spans:
        return None
    gen_lines = generated_text.splitlines()
    orig = _slice_span(gen_lines, spans[orig_key])
    mut = _slice_span(gen_lines, spans[mut_key])
    if orig is None or mut is None:
        return None
    di = def_index(orig)
    rel = mutated_rel_index(orig, mut)
    if di is None or rel is None:
        return None
    return base_line + (rel - di)


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
def classify(
    survivors: Iterable[tuple[str, str]],
    changed_lines: Mapping[str, set[int]],
    allowlist: set[str],
    resolve_line: Callable[[str], tuple[str, int] | None],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Split survivors into ``(introduced, legacy, allowlisted, fatal)``.

    ``resolve_line`` returns ``(source_path, line)`` or None. Only ``survived``
    mutants are routed by location: None -> INTRODUCED (fail-closed); a name in
    the allowlist -> ALLOWLISTED; a located line inside the diff -> INTRODUCED;
    otherwise LEGACY. Fatal statuses (timeout/suspicious/segfault/no tests) go
    to FATAL regardless of location or allowlist, so they always block.
    """
    introduced: list[str] = []
    legacy: list[str] = []
    allowlisted: list[str] = []
    fatal: list[str] = []
    for name, status in survivors:
        if status in FATAL_STATUSES:
            fatal.append(name)  # always blocks, independent of location/allowlist
            continue
        if name in allowlist:
            allowlisted.append(name)
            continue
        located = resolve_line(name)
        if located is None:
            introduced.append(name)  # fail-closed
            continue
        path, line = located
        if line in changed_lines.get(path, set()):
            introduced.append(name)
        else:
            legacy.append(name)
    return introduced, legacy, allowlisted, fatal


# --------------------------------------------------------------------------- #
# I/O glue (only main touches the filesystem / subprocesses)
# --------------------------------------------------------------------------- #
def _run_git(args: list[str], cwd: Path) -> str | None:
    try:
        proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    except OSError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def _merge_base(cwd: Path) -> str | None:
    for ref in ("origin/main", "main"):
        out = _run_git(["merge-base", "HEAD", ref], cwd)
        if out and out.strip():
            return out.strip()
    return None


def make_resolver(mutants_dir: Path, source_root: str) -> Callable[[str], tuple[str, int] | None]:
    """Build a cached survivor->(path,line) resolver from on-disk mutmut artifacts."""
    cache: dict[str, tuple[dict | None, str | None, str | None]] = {}

    def resolve(name: str) -> tuple[str, int] | None:
        parsed = split_survivor_name(name)
        if not parsed:
            return None
        module, _span_key, _n = parsed
        if module not in cache:
            path = module_to_path(module, source_root)
            spans = _load_spans(mutants_dir / f"{path}.spans")
            cache[module] = (spans, _read(mutants_dir / path), _read(Path(path)))
        spans, generated, source = cache[module]
        if spans is None or generated is None or source is None:
            return None
        line = resolve_survivor_line(name, spans, generated, source)
        return None if line is None else (module_to_path(module, source_root), line)

    return resolve


def _load_spans(spans_path: Path) -> dict | None:
    try:
        data = json.loads(spans_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("version") != 1 or not isinstance(data.get("spans"), dict):
        return None
    return data["spans"]


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0912 - linear CLI glue: parse, gather, classify, report
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", type=Path)
    parser.add_argument("--mutants-dir", default="mutants", type=Path)
    parser.add_argument("--source-root", default="src")
    parser.add_argument("--allowlist", default=".github/mutmut-equivalents.txt", type=Path)
    parser.add_argument("--base", default=None, help="git ref; defaults to merge-base with main")
    parser.add_argument(
        "--results-file", default=None, type=Path, help="read mutmut results from a file"
    )
    args = parser.parse_args(argv)

    repo_root: Path = args.repo_root
    mutants_dir: Path = args.mutants_dir
    if not mutants_dir.is_absolute():
        mutants_dir = repo_root / mutants_dir

    base = args.base or _merge_base(repo_root)
    if base is None:
        print("ERROR: could not determine merge-base with main", file=sys.stderr)
        return 1

    diff = _run_git(["diff", "--unified=0", base, "HEAD", "--", args.source_root], repo_root)
    if diff is None:
        print("ERROR: git diff failed", file=sys.stderr)
        return 1
    changed_lines = parse_changed_lines(diff)

    if args.results_file is not None:
        results_text = _read(args.results_file)
    else:
        try:
            proc = subprocess.run(
                ["mutmut", "results"], cwd=repo_root, capture_output=True, text=True, check=False
            )
            results_text = proc.stdout
        except OSError:
            results_text = None
    if results_text is None:
        print("ERROR: could not read mutmut results", file=sys.stderr)
        return 1
    survivors = parse_results(results_text)

    allowlist_path = args.allowlist
    if not allowlist_path.is_absolute():
        allowlist_path = repo_root / allowlist_path
    allowlist_text = _read(allowlist_path)
    allowlist = load_allowlist(allowlist_text or "")

    resolver = make_resolver(mutants_dir, args.source_root)
    introduced, legacy, allowlisted, fatal = classify(survivors, changed_lines, allowlist, resolver)

    print(
        f"survivors: {len(survivors)}  introduced: {len(introduced)}  "
        f"legacy: {len(legacy)}  allowlisted: {len(allowlisted)}  fatal: {len(fatal)}"
    )
    for name in fatal:
        print(f"  FATAL: {name}")
    for name in introduced:
        print(f"  INTRODUCED: {name}")
    for name in legacy:
        print(f"  LEGACY: {name}")
    for name in allowlisted:
        print(f"  ALLOWLISTED: {name}")

    if fatal or introduced:
        print(
            f"FAIL: {len(fatal)} fatal survivor(s); "
            f"{len(introduced)} introduced survivor(s) not in allowlist",
            file=sys.stderr,
        )
        return 1
    print("PASS: no unexpected introduced survivors and no fatal mutants")
    return 0


if __name__ == "__main__":
    sys.exit(main())
