"""Unit tests for the epistemic-triage evidence harness (.pre-commit/mutation_evidence.py).

Pure-rule tests plus an end-to-end check on a tiny synthetic artifact that
exercises every disposition, and the read-only / determinism guarantees.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _locate(name: str) -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / ".pre-commit" / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(name)


_spec = importlib.util.spec_from_file_location("mutation_evidence", _locate("mutation_evidence.py"))
assert _spec is not None and _spec.loader is not None
me = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = me
_spec.loader.exec_module(me)


# --------------------------------------------------------------------------- #
# string_context / literal_of
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ('    raise ValueError("bad input")', "MESSAGE"),
        ('    logger.info("hello")', "MESSAGE"),
        ('    if s.startswith("http"):', "COMPARED"),
        ('    x = d.get("k", 0)', "COMPARED"),
        ('    "id": "",', "DICT_KEY"),
        ('    sql = "SELECT * FROM t WHERE a"', "SQL"),
        ('    p = Path("docs")', "PATH"),
        ('    return "plain"', "OTHER"),
    ],
)
def test_string_context(line, expected):
    assert me.string_context(line) == expected


def test_literal_of():
    assert me.literal_of('    raise ValueError("bad input")') == "bad input"
    assert me.literal_of("    return 42") is None


# --------------------------------------------------------------------------- #
# suggest_disposition (the contract criterion, as a hint)
# --------------------------------------------------------------------------- #
def test_message_absent_is_equivalent_candidate():
    assert (
        me.suggest_disposition(me.STRING_MUTATION, "MESSAGE", False, True)
        == me.EQUIVALENT_CANDIDATE
    )


def test_message_present_is_review():
    assert me.suggest_disposition(me.STRING_MUTATION, "MESSAGE", True, True) == me.NEEDS_REVIEW


def test_compared_is_contract_test():
    assert me.suggest_disposition(me.STRING_MUTATION, "COMPARED", False, True) == me.CONTRACT_TEST


def test_sql_absent_is_coverage_gap():
    assert me.suggest_disposition(me.STRING_MUTATION, "SQL", False, True) == me.COVERAGE_GAP


def test_arg_removal_tested_vs_untested():
    assert me.suggest_disposition("ARG_REMOVAL", "n/a", None, True) == me.CONTRACT_TEST
    assert me.suggest_disposition("ARG_REMOVAL", "n/a", None, False) == me.COVERAGE_GAP


def test_unknown_is_review():
    assert me.suggest_disposition(me.UNKNOWN, "n/a", None, True) == me.NEEDS_REVIEW


def test_site_id_is_stable():
    a = me._site_id("f.py", "mod.x", "STRING_MUTATION", "line")
    assert a == me._site_id("f.py", "mod.x", "STRING_MUTATION", "line")
    assert a != me._site_id("f.py", "mod.x", "STRING_MUTATION", "other")


# --------------------------------------------------------------------------- #
# synthetic artifact
# --------------------------------------------------------------------------- #
_GEN = (
    "def x__msg__mutmut_orig():\n"
    '    raise ValueError("bad input")\n'
    "def x__msg__mutmut_1():\n"
    '    raise ValueError("XXbad inputXX")\n'
    "def x__cmp__mutmut_orig(s):\n"
    '    return s.startswith("http")\n'
    "def x__cmp__mutmut_1(s):\n"
    '    return s.startswith("XXhttpXX")\n'
    "def x__arg__mutmut_orig(a, b):\n"
    "    return foo(a, b)\n"
    "def x__arg__mutmut_1(a, b):\n"
    "    return foo(None, b)\n"
    "def x__arg2__mutmut_orig(a, b):\n"
    "    return bar(a, b)\n"
    "def x__arg2__mutmut_1(a, b):\n"
    "    return bar(b)\n"
)
_SPANS = {
    "x__msg__mutmut_orig": [1, 2],
    "x__msg__mutmut_1": [3, 4],
    "x__cmp__mutmut_orig": [5, 6],
    "x__cmp__mutmut_1": [7, 8],
    "x__arg__mutmut_orig": [9, 10],
    "x__arg__mutmut_1": [11, 12],
    "x__arg2__mutmut_orig": [13, 14],
    "x__arg2__mutmut_1": [15, 16],
}


def _write_artifact(root: Path) -> Path:
    art = root / "art"
    src = art / "src" / "pkg"
    src.mkdir(parents=True)
    (src / "mod.py").write_text(_GEN, encoding="utf-8")
    (src / "mod.py.spans").write_text(json.dumps({"version": 1, "spans": _SPANS}), encoding="utf-8")
    (src / "mod.py.meta").write_text(
        json.dumps(
            {
                "exit_code_by_key": {
                    f"pkg.mod.x__{fn}__mutmut_1": 0 for fn in ("msg", "cmp", "arg", "arg2")
                }
            }
        ),
        encoding="utf-8",
    )
    (art / "mutmut-cicd-stats.json").write_text(
        json.dumps(
            {"killed": 0, "survived": 4, "no_tests": 0, "timeout": 0, "total": 4, "skipped": 0}
        ),
        encoding="utf-8",
    )
    (art / "mutmut-stats.json").write_text(
        json.dumps(
            {
                "tests_by_mangled_function_name": {
                    "pkg.mod.x__msg": ["t"],
                    "pkg.mod.x__cmp": ["t"],
                    "pkg.mod.x__arg": ["t"],
                    "pkg.mod.x__arg2": [],
                }
            }
        ),
        encoding="utf-8",
    )
    return art


def _sites(art: Path):
    return me.build_sites(
        art,
        tests_blob="nothing relevant here",
        tests_by_func={
            "pkg.mod.x__msg": ["t"],
            "pkg.mod.x__cmp": ["t"],
            "pkg.mod.x__arg": ["t"],
            "pkg.mod.x__arg2": [],
        },
    )


def test_build_sites_dispositions(tmp_path):
    art = _write_artifact(tmp_path)
    disp = {s.func.rsplit(".", 1)[-1]: s.suggested_disposition for s in _sites(art)}
    assert disp["x__msg"] == me.EQUIVALENT_CANDIDATE  # MESSAGE, literal not in tests
    assert disp["x__cmp"] == me.CONTRACT_TEST  # COMPARED
    assert disp["x__arg"] == me.CONTRACT_TEST  # ARG_REMOVAL, func has test
    assert disp["x__arg2"] == me.COVERAGE_GAP  # ARG_REMOVAL, func has no test


def test_summarize_counts(tmp_path):
    art = _write_artifact(tmp_path)
    summary = me.summarize(_sites(art))
    assert summary["sites"] == 4
    assert summary["by_disposition"][me.EQUIVALENT_CANDIDATE] == 1
    assert summary["by_disposition"][me.CONTRACT_TEST] == 2
    assert summary["by_disposition"][me.COVERAGE_GAP] == 1


def test_render_log_lists_sites(tmp_path):
    art = _write_artifact(tmp_path)
    md = me.render_log_md(_sites(art))
    assert "# Mutation Triage Log" in md
    assert "EQUIVALENT_CANDIDATE" in md
    assert "disposition:" in md


# --------------------------------------------------------------------------- #
# guarantees: read-only + determinism (end to end via main)
# --------------------------------------------------------------------------- #
def _hash_tree(root: Path) -> dict:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _run_main(art: Path, out: Path, tests_dir: Path) -> int:
    return me.main(["--mutants-dir", str(art), "--out", str(out), "--tests-dir", str(tests_dir)])


def test_evidence_readonly_and_deterministic(tmp_path):
    art = _write_artifact(tmp_path)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "t.py").write_text("def test_x():\n    assert 1\n", encoding="utf-8")
    before = _hash_tree(art)
    o1, o2 = tmp_path / "o1", tmp_path / "o2"
    assert _run_main(art, o1, tests) == 0
    assert _run_main(art, o2, tests) == 0
    assert _hash_tree(art) == before  # artifact untouched
    for name in ("evidence.json", "triage-log.md"):
        assert (o1 / name).read_bytes() == (o2 / name).read_bytes()  # deterministic


def test_evidence_missing_artifact(tmp_path):
    assert me.main(["--mutants-dir", str(tmp_path / "nope"), "--out", str(tmp_path / "o")]) == 2


def test_module_has_main():
    assert callable(me.main)
