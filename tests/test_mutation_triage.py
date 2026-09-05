"""Unit tests for mutation triage (.pre-commit/mutation_triage.py).

Uses a tiny synthetic mutmut artifact built under pytest's ``tmp_path`` so the
read-only and determinism guarantees are checked for real, end to end.
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


_spec = importlib.util.spec_from_file_location("mutation_triage", _locate("mutation_triage.py"))
assert _spec is not None and _spec.loader is not None
mt = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mt
_spec.loader.exec_module(mt)


# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #
def test_split_mutant_key():
    assert mt.split_mutant_key("pkg.mod.x__cmp__mutmut_1") == ("pkg.mod", "x__cmp", "1")


def test_split_mutant_key_rejects_bad():
    assert mt.split_mutant_key("no_index_here") is None
    assert mt.split_mutant_key("x__f__mutmut_2") is None  # no module dot


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (0, "survived"),
        (1, "killed"),
        (33, "no tests"),
        (-24, "timeout"),
        (None, "not checked"),
        (999, "suspicious"),
    ],
)
def test_status_for(code, status):
    assert mt.status_for(code) == status


def test_rank_sorts_by_count_then_key():
    from collections import Counter

    assert mt._rank(Counter({"b": 2, "a": 2, "c": 5})) == [["c", 5], ["a", 2], ["b", 2]]


# --------------------------------------------------------------------------- #
# synthetic artifact fixture
# --------------------------------------------------------------------------- #
def _write_artifact(root: Path) -> Path:
    art = root / "art"
    src = art / "src" / "pkg"
    src.mkdir(parents=True)
    (src / "mod.py").write_text(
        "def x__cmp__mutmut_orig(x):\n"
        "    return x < 1\n"
        "def x__cmp__mutmut_1(x):\n"
        "    return x <= 1\n"
        "def x__nt__mutmut_orig(x):\n"
        "    return x < 1\n"
        "def x__nt__mutmut_1(x):\n"
        "    return x <= 1\n",
        encoding="utf-8",
    )
    (src / "mod.py.spans").write_text(
        json.dumps(
            {
                "version": 1,
                "spans": {
                    "x__cmp__mutmut_orig": [1, 2],
                    "x__cmp__mutmut_1": [3, 4],
                    "x__nt__mutmut_orig": [5, 6],
                    "x__nt__mutmut_1": [7, 8],
                },
            }
        ),
        encoding="utf-8",
    )
    (src / "mod.py.meta").write_text(
        json.dumps(
            {
                "exit_code_by_key": {
                    "pkg.mod.x__cmp__mutmut_1": 0,
                    "pkg.mod.x__cmp__mutmut_2": 1,
                    "pkg.mod.x__nt__mutmut_1": 33,
                }
            }
        ),
        encoding="utf-8",
    )
    (art / "mutmut-cicd-stats.json").write_text(
        json.dumps(
            {"killed": 1, "survived": 1, "no_tests": 1, "timeout": 0, "total": 3, "skipped": 0}
        ),
        encoding="utf-8",
    )
    return art


def _hash_tree(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# --------------------------------------------------------------------------- #
# build_records / reconcile / aggregate
# --------------------------------------------------------------------------- #
def test_build_records_classifies_survived_and_notests(tmp_path):
    art = _write_artifact(tmp_path)
    records = mt.build_records(art, set(), mt.HybridClassifier())
    by_status = {r.status: r for r in records}
    assert set(by_status) == {"survived", "no tests"}  # killed excluded
    assert by_status["survived"].category == "RELATIONAL_OPERATOR"
    assert by_status["survived"].allowlisted is False


def test_reconcile_ok_and_fail(tmp_path):
    art = _write_artifact(tmp_path)
    records = mt.build_records(art, set(), mt.HybridClassifier())
    assert mt.reconcile(records, {"survived": 1, "no_tests": 1, "timeout": 0})["ok"] is True
    assert mt.reconcile(records, {"survived": 5, "no_tests": 1, "timeout": 0})["ok"] is False


def test_aggregate_buckets(tmp_path):
    art = _write_artifact(tmp_path)
    records = mt.build_records(art, set(), mt.HybridClassifier())
    agg = mt.aggregate(records, top=10)
    assert agg["by_status"] == {"no tests": 1, "survived": 1}
    assert agg["by_category"] == [["RELATIONAL_OPERATOR", 1]]
    assert agg["by_file"] == [["src/pkg/mod.py", 1]]


# --------------------------------------------------------------------------- #
# end-to-end guarantees: read-only + determinism
# --------------------------------------------------------------------------- #
def _run_main(art: Path, out: Path) -> int:
    empty = art.parent / "allow.txt"
    empty.write_text("# none\n", encoding="utf-8")
    return mt.main(["--mutants-dir", str(art), "--out", str(out), "--allowlist", str(empty)])


def test_triage_is_readonly_and_writes_only_to_out(tmp_path):
    art = _write_artifact(tmp_path)
    out = tmp_path / "out"
    before = _hash_tree(art)
    assert _run_main(art, out) == 0
    assert _hash_tree(art) == before  # artifact untouched
    assert (out / "mutation-triage.json").is_file()
    assert (out / "mutation-triage.md").is_file()


def test_triage_is_deterministic(tmp_path):
    art = _write_artifact(tmp_path)
    o1, o2 = tmp_path / "o1", tmp_path / "o2"
    assert _run_main(art, o1) == 0
    assert _run_main(art, o2) == 0
    for name in ("mutation-triage.json", "mutation-triage.md"):
        assert (o1 / name).read_bytes() == (o2 / name).read_bytes()


def test_triage_missing_artifact_dir(tmp_path):
    assert mt.main(["--mutants-dir", str(tmp_path / "nope"), "--out", str(tmp_path / "o")]) == 2


def test_module_has_main():
    assert callable(mt.main)
