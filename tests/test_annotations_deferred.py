"""Convention guard: TYPE_CHECKING imports require deferred annotations.

On Python < 3.14, annotations are evaluated eagerly (at def time / module
level). A module that imports names under ``if TYPE_CHECKING:`` but references
them in an annotation without ``from __future__ import annotations`` raises
NameError at import time on the CI interpreter (3.12) while passing locally
on 3.14 (PEP 649 lazy annotations). This scan keeps that class of bug out of
the codebase, version-independently.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "aios"


def _module_flags(source: str) -> tuple[bool, bool]:
    """Return (has_future_annotations, has_type_checking_block)."""
    tree = ast.parse(source)
    has_future = False
    has_tch = False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "__future__"
            and any(a.name == "annotations" for a in node.names)
        ):
            has_future = True
        if isinstance(node, ast.If):
            test = node.test
            is_tch_guard = (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
                isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
            )
            if is_tch_guard and any(
                isinstance(stmt, (ast.Import, ast.ImportFrom)) for stmt in node.body
            ):
                has_tch = True
    return has_future, has_tch


def test_every_type_checking_module_defers_annotations():
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        try:
            has_future, has_tch = _module_flags(source)
        except SyntaxError:  # pragma: no cover
            raise
        if has_tch and not has_future:
            offenders.append(path.relative_to(SRC.parent).as_posix())
    assert not offenders, (
        "modules with TYPE_CHECKING imports must have "
        f"'from __future__ import annotations': {offenders}"
    )
