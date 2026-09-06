"""Unit tests for mutation_string_proofs.py — the evidence dossier for EQUIVALENT_CANDIDATE sites."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".pre-commit"))

_spec = importlib.util.spec_from_file_location(
    "mutation_string_proofs",
    Path(__file__).resolve().parent.parent / ".pre-commit" / "mutation_string_proofs.py",
)
assert _spec is not None and _spec.loader is not None
sp = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = sp
_spec.loader.exec_module(sp)


# --------------------------------------------------------------------------- #
# classify_context_kind
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ('    raise TypeError("expected Task")', "RAISE"),
        ('    click.echo("done")', "CLI"),
        ('    console.print("output")', "CLI"),
        ('    "Usage: aios foo <bar>"', "HELP"),
        ('    "  --verbose  Enable verbose mode"', "HELP"),
        ('    logger.debug("entering function")', "LOG"),
        ('    logging.warning("deprecated")', "LOG"),
        ('    """Returns the result."""', "DOCSTRING"),
        ('    x = "plain string"', "OTHER"),
    ],
)
def test_classify_context_kind(line, expected):
    assert sp.classify_context_kind(line) == expected


# --------------------------------------------------------------------------- #
# source_context extraction (fallback path, no libcst needed)
# --------------------------------------------------------------------------- #
def test_extract_by_dedent_finds_function():
    src = "import os\n\ndef foo(x):\n    return x + 1\n\ndef bar():\n    pass\n"
    result = sp._extract_by_dedent(src, "foo")
    assert result is not None
    start, end, code = result
    assert start == 3
    assert end == 4  # stops at blank line (not including it)
    assert "return x + 1" in code


def test_extract_by_dedent_returns_none_if_missing():
    assert sp._extract_by_dedent("def foo(): pass", "bar") is None


# --------------------------------------------------------------------------- #
# test_locations
# --------------------------------------------------------------------------- #
def test_find_test_locations_sorted(tmp_path):
    t = tmp_path / "tests"
    t.mkdir()
    (t / "a.py").write_text('x = "needle"\n', encoding="utf-8")
    (t / "b.py").write_text('y = "needle"\n', encoding="utf-8")
    locs = sp._find_test_locations("needle", t)
    assert len(locs) == 2
    assert locs[0]["file"] < locs[1]["file"]  # deterministic sort


def test_find_test_locations_limit():
    assert sp._find_test_locations(None, Path(".")) == []


# --------------------------------------------------------------------------- #
# build_proofs end-to-end
# --------------------------------------------------------------------------- #
def _make_evidence(out: Path) -> Path:
    """Write a minimal evidence.json with 2 EQUIVALENT_CANDIDATE sites."""
    payload = {
        "sites": [
            {
                "site_id": "aaa",
                "file": "src/pkg/mod.py",
                "func": "pkg.mod.x__msg",
                "module": "pkg.mod",
                "category": "STRING_MUTATION",
                "status": "survived",
                "context": "MESSAGE",
                "orig_literal": "bad input",
                "literal_in_tests": False,
                "func_has_test": True,
                "suggested_disposition": "EQUIVALENT_CANDIDATE",
                "mutant_ids": ["pkg.mod.x__msg__mutmut_1"],
            },
            {
                "site_id": "bbb",
                "file": "src/pkg/mod.py",
                "func": "pkg.mod.x__cmp",
                "module": "pkg.mod",
                "category": "STRING_MUTATION",
                "status": "survived",
                "context": "COMPARED",
                "orig_literal": "http",
                "literal_in_tests": True,
                "func_has_test": True,
                "suggested_disposition": "CONTRACT_TEST",
                "mutant_ids": ["pkg.mod.x__cmp__mutmut_1"],
            },
        ]
    }
    (out / "evidence.json").write_text(json.dumps(payload), encoding="utf-8")
    return out / "evidence.json"


def _make_source(root: Path):
    src = root / "src" / "pkg"
    src.mkdir(parents=True)
    (src / "mod.py").write_text('def _msg():\n    raise TypeError("bad input")\n', encoding="utf-8")


def test_build_proofs_filters_and_enriches(tmp_path):
    evidence = _make_evidence(tmp_path)
    _make_source(tmp_path)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "t.py").write_text('x = "bad input"\n', encoding="utf-8")
    proofs = sp.build_proofs(evidence, tmp_path, tests)
    assert len(proofs) == 1  # CONTRACT_TEST filtered out
    p = proofs[0]
    assert p.context_kind == "RAISE"
    assert p.literal_original == "bad input"
    assert p.literal_in_tests is True
    assert len(p.test_locations) == 1
    assert p.source_context is not None
    assert p.human_disposition is None


def test_build_proofs_empty_when_no_candidates(tmp_path):
    payload = {"sites": [{"suggested_disposition": "CONTRACT_TEST", "site_id": "x"}]}
    (tmp_path / "evidence.json").write_text(json.dumps(payload), encoding="utf-8")
    assert sp.build_proofs(tmp_path / "evidence.json", tmp_path, tmp_path / "tests") == []


# --------------------------------------------------------------------------- #
# determinism + read-only
# --------------------------------------------------------------------------- #
def _hash_tree(root: Path) -> dict:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_proofs_deterministic_and_readonly(tmp_path):
    evidence = _make_evidence(tmp_path)
    _make_source(tmp_path)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "t.py").write_text('x = "bad input"\n', encoding="utf-8")
    out1 = tmp_path / "o1"
    out2 = tmp_path / "o2"
    # hash only INPUT files (not output dirs)
    inputs = [evidence, tmp_path / "src/pkg/mod.py", tests / "t.py"]
    before = {
        str(p.relative_to(tmp_path)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs
    }
    sp.main(
        [
            "--evidence",
            str(evidence),
            "--repo-root",
            str(tmp_path),
            "--tests-dir",
            str(tests),
            "--out",
            str(out1),
        ]
    )
    sp.main(
        [
            "--evidence",
            str(evidence),
            "--repo-root",
            str(tmp_path),
            "--tests-dir",
            str(tests),
            "--out",
            str(out2),
        ]
    )
    after = {
        str(p.relative_to(tmp_path)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs
    }
    assert before == after  # inputs unchanged
    assert (out1 / "evidence-string-proofs.json").read_bytes() == (
        out2 / "evidence-string-proofs.json"
    ).read_bytes()
    assert (out1 / "evidence-string-proofs.md").read_bytes() == (
        out2 / "evidence-string-proofs.md"
    ).read_bytes()


def test_missing_evidence_returns_2():
    assert sp.main(["--evidence", "/nonexistent.json", "--out", "/tmp/o"]) == 2


def test_module_has_main():
    assert callable(sp.main)
