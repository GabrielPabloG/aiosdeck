"""Deterministic review detectors — file-level scans for ReviewerAgent.

Each ``_scan_*`` function inspects a single file's source text and returns a
list of finding dicts. Detectors are pure (no I/O, no runtime) so they are
trivially testable and run identically in CI and locally.
"""

import re

_LONG_FUNCTION_LINES = 60

_TODO_PATTERN = re.compile(r"(?i)#\s*(todo|fixme|hack|xxx)\b")
_SECRET_PATTERN = re.compile(
    r"(?i)\b(?:password|passwd|api[_-]?key|secret|access[_-]?token|auth[_-]?token)\b\s*[:=]\s*[\"'][^\"'\s]+[\"']"
)
_UNSAFE_PATTERN = re.compile(r"\b(?:eval|exec)\s*\(")
_FUNC_DEF_PATTERN = re.compile(r"\s*def\s+\w+\s*\(")

_SUGGESTIONS = {
    "todo-detection": "Replace the TODO with a tracked issue reference (text only)",
    "missing-module-docstring": "Add a module-level docstring describing its purpose",
    "long-function": "Extract smaller, focused functions from the body",
    "hardcoded-secret": "Move the secret to an environment variable or Secret Manager",
    "unsafe-eval": "Use json.loads / ast.literal_eval instead of eval/exec",
}


def _item(rule: str, severity: str, file: str, line: int, message: str) -> dict:
    return {
        "id": "",
        "rule": rule,
        "severity": severity,
        "file": file,
        "line": line,
        "message": message,
        "suggestion": _SUGGESTIONS.get(rule, ""),
    }


def scan_todos(text: str, rel: str) -> list[dict]:
    items = []
    for i, line in enumerate(text.splitlines(), start=1):
        match = _TODO_PATTERN.search(line)
        if match:
            items.append(
                _item(
                    "todo-detection",
                    "info",
                    rel,
                    i,
                    f"TODO/FIXME comment: {match.group(1).upper()}",
                )
            )
    return items


def scan_docstrings(text: str, rel: str) -> list[dict]:
    stripped = text.lstrip()
    if stripped.startswith(('"""', "'''")):
        return []
    first = next(
        (ln for ln in stripped.splitlines() if ln.strip() and not ln.lstrip().startswith("#")),
        "",
    )
    if first:
        return [_item("missing-module-docstring", "warning", rel, 1, "Module missing a docstring")]
    return []


def _find_function_end(lines: list[str], start: int, indent: int) -> int:
    for j in range(start, len(lines)):
        line = lines[j]
        if not line.strip() or line.strip().startswith("#"):
            continue
        if len(line) - len(line.lstrip()) <= indent:
            return j
    return len(lines)


def scan_long_functions(text: str, rel: str) -> list[dict]:
    items = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not _FUNC_DEF_PATTERN.match(line):
            continue
        indent = len(line) - len(line.lstrip())
        end = _find_function_end(lines, i + 1, indent)
        length = end - i
        if length > _LONG_FUNCTION_LINES:
            name = line.strip().split("(", 1)[0].split()[-1]
            items.append(
                _item(
                    "long-function",
                    "info",
                    rel,
                    i + 1,
                    f"Function {name} is {length} lines long",
                )
            )
    return items


def scan_secrets(text: str, rel: str) -> list[dict]:
    return [
        _item("hardcoded-secret", "error", rel, i, "Potential hardcoded secret")
        for i, line in enumerate(text.splitlines(), start=1)
        if _SECRET_PATTERN.search(line)
    ]


def scan_unsafe(text: str, rel: str) -> list[dict]:
    return [
        _item("unsafe-eval", "warning", rel, i, "Use of eval/exec is discouraged")
        for i, line in enumerate(text.splitlines(), start=1)
        if _UNSAFE_PATTERN.search(line)
    ]


def compute_stats(items: list[dict]) -> dict:
    stats = {"errors": 0, "warnings": 0, "infos": 0}
    for item in items:
        severity = item["severity"]
        if severity == "error":
            stats["errors"] += 1
        elif severity == "warning":
            stats["warnings"] += 1
        else:
            stats["infos"] += 1
    return stats


def build_summary(items: list[dict], stats: dict) -> str:
    total = len(items)
    return (
        f"Found {total} item(s): {stats['errors']} error(s), "
        f"{stats['warnings']} warning(s), {stats['infos']} info(s)"
    )
