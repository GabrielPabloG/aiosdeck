"""Unit tests for the mutation-gate classifier (.pre-commit/check_mutation_gate.py).

All inputs are synthetic (fake diff / mutmut results / .spans / generated file /
source) so the algorithm is validated without running mutmut.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_mutation_gate", _ROOT / ".pre-commit" / "check_mutation_gate.py"
)
assert _spec is not None and _spec.loader is not None
cmg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cmg)

SEP = cmg.CLASS_SEP


# --------------------------------------------------------------------------- #
# parse_changed_lines
# --------------------------------------------------------------------------- #
def test_parse_changed_lines_single_hunk():
    diff = "--- a/src/x.py\n+++ b/src/x.py\n@@ -1,2 +3,2 @@\n"
    assert cmg.parse_changed_lines(diff) == {"src/x.py": {3, 4}}


def test_parse_changed_lines_multiple_hunks_same_file():
    diff = "--- a/src/x.py\n+++ b/src/x.py\n@@ -1,0 +2,2 @@\n@@ -20,1 +25,1 @@\n"
    assert cmg.parse_changed_lines(diff) == {"src/x.py": {2, 3, 25}}


def test_parse_changed_lines_insertion_no_added_lines():
    # +5,0 means zero added lines (pure deletion / insertion point)
    diff = "--- a/src/x.py\n+++ b/src/x.py\n@@ -5,1 +5,0 @@\n"
    assert cmg.parse_changed_lines(diff) == {"src/x.py": set()}


def test_parse_changed_lines_bare_plus_is_one_line():
    diff = "--- a/src/x.py\n+++ b/src/x.py\n@@ -9 +12 @@\n"
    assert cmg.parse_changed_lines(diff) == {"src/x.py": {12}}


def test_parse_changed_lines_multi_file():
    diff = (
        "--- a/src/x.py\n+++ b/src/x.py\n@@ -1 +1 @@\n"
        "--- a/src/y.py\n+++ b/src/y.py\n@@ -4 +7,2 @@\n"
    )
    assert cmg.parse_changed_lines(diff) == {"src/x.py": {1}, "src/y.py": {7, 8}}


# --------------------------------------------------------------------------- #
# name / span_key parsing
# --------------------------------------------------------------------------- #
def test_split_survivor_name_module_func():
    assert cmg.split_survivor_name("pkg.mod.x__parse__mutmut_11") == ("pkg.mod", "x__parse", "11")


def test_split_survivor_name_method():
    name = f"pkg.mod.x{SEP}Foo{SEP}bar__mutmut_3"
    assert cmg.split_survivor_name(name) == ("pkg.mod", f"x{SEP}Foo{SEP}bar", "3")


def test_split_survivor_name_rejects_bad():
    assert cmg.split_survivor_name("no_index_here") is None  # no __mutmut_N suffix
    assert cmg.split_survivor_name("x__f__mutmut_1") is None  # no module dot


def test_span_key_to_class_func_module():
    assert cmg.span_key_to_class_func("x__parse") == (None, "_parse")


def test_span_key_to_class_func_method():
    assert cmg.span_key_to_class_func(f"x{SEP}Foo{SEP}bar") == ("Foo", "bar")


def test_span_key_to_class_func_rejects_short():
    assert cmg.span_key_to_class_func(f"x{SEP}Only") is None
    assert cmg.span_key_to_class_func("noprefix") is None


def test_module_to_path():
    assert cmg.module_to_path("aios.workflow.engine", "src") == "src/aios/workflow/engine.py"


# --------------------------------------------------------------------------- #
# AST function location
# --------------------------------------------------------------------------- #
_SRC_METHOD = "class Foo:\n    @staticmethod\n    def bar(x):\n        return x + 1\n"


def test_func_def_line_method_with_decorator():
    assert cmg.func_def_line(_SRC_METHOD, "Foo", "bar") == 3  # the `def` line, not the decorator


def test_func_def_line_module_func():
    src = "def _parse(x):\n    return x\n"
    assert cmg.func_def_line(src, None, "_parse") == 1


def test_func_def_line_missing_returns_none():
    assert cmg.func_def_line(_SRC_METHOD, "Foo", "nope") is None
    assert cmg.func_def_line(_SRC_METHOD, "NoClass", "bar") is None


def test_func_def_line_ambiguous_returns_none():
    src = "def f():\n    pass\ndef f():\n    pass\n"
    assert cmg.func_def_line(src, None, "f") is None


def test_func_def_line_syntax_error_returns_none():
    assert cmg.func_def_line("def (:", None, "x") is None


def test_def_index_skips_leading_blank():
    assert cmg.def_index(["", "def f():", "    pass"]) == 1


def test_def_index_none_when_no_def():
    assert cmg.def_index(["", "    not a def"]) is None


# --------------------------------------------------------------------------- #
# mutated_rel_index
# --------------------------------------------------------------------------- #
def test_mutated_rel_index_single_line():
    orig = ["def f(x):", "    return x + 1"]
    mut = ["def f(x):", "    return x + 2"]
    assert cmg.mutated_rel_index(orig, mut) == 1


def test_mutated_rel_index_ignores_rename_only():
    # only the def line differs (function renamed) -> no real mutation
    orig = ["def f__mutmut_orig(x):", "    return x"]
    mut = ["def f__mutmut_1(x):", "    return x"]
    assert cmg.mutated_rel_index(orig, mut) is None


def test_mutated_rel_index_multiple_disjoint_is_none():
    orig = ["def f():", "    a = 1", "    b = 2", "    c = 3", "    return c"]
    mut = ["def f():", "    a = 9", "    b = 2", "    c = 8", "    return c"]
    assert cmg.mutated_rel_index(orig, mut) is None


def test_mutated_rel_index_length_change_insert():
    orig = ["def f():", "    return 1"]
    mut = ["def f():", "    x = 0", "    return 1"]
    assert cmg.mutated_rel_index(orig, mut) == 1


# --------------------------------------------------------------------------- #
# resolve_survivor_line (end-to-end location)
# --------------------------------------------------------------------------- #
def _method_fixture():
    gen = (
        "\n"
        f"def x{SEP}Foo{SEP}bar__mutmut_orig(x):\n"
        "    return x + 1\n"
        "\n"
        f"def x{SEP}Foo{SEP}bar__mutmut_1(x):\n"
        "    return x + 2\n"
    )
    spans = {
        f"x{SEP}Foo{SEP}bar__mutmut_orig": [2, 3],
        f"x{SEP}Foo{SEP}bar__mutmut_1": [5, 6],
    }
    name = f"pkg.mod.x{SEP}Foo{SEP}bar__mutmut_1"
    return name, spans, gen, _SRC_METHOD


def test_resolve_survivor_line_method():
    name, spans, gen, src = _method_fixture()
    # def bar is real line 3; mutation is the `return` line -> 4
    assert cmg.resolve_survivor_line(name, spans, gen, src) == 4


def test_resolve_survivor_line_module_func():
    src = "def _parse(x):\n    return x\n"
    gen = (
        "\n"
        "def x__parse__mutmut_orig(x):\n"
        "    return x\n"
        "\n"
        "def x__parse__mutmut_1(x):\n"
        "    return y\n"
    )
    spans = {"x__parse__mutmut_orig": [2, 3], "x__parse__mutmut_1": [5, 6]}
    assert cmg.resolve_survivor_line("pkg.x__parse__mutmut_1", spans, gen, src) == 2


def test_resolve_survivor_line_missing_span_is_none():
    name, spans, gen, src = _method_fixture()
    assert cmg.resolve_survivor_line(name, {}, gen, src) is None


def test_resolve_survivor_line_ambiguous_diff_is_none():
    src = "class Foo:\n    def bar(self):\n        a=1\n        b=2\n        c=3\n        d=4\n"
    gen = (
        f"def x{SEP}Foo{SEP}bar__mutmut_orig(self):\n"
        "    a=1\n    b=2\n    c=3\n    d=4\n"
        f"def x{SEP}Foo{SEP}bar__mutmut_1(self):\n"
        "    a=9\n    b=2\n    c=8\n    d=4\n"
    )
    spans = {f"x{SEP}Foo{SEP}bar__mutmut_orig": [1, 5], f"x{SEP}Foo{SEP}bar__mutmut_1": [6, 10]}
    assert cmg.resolve_survivor_line(f"pkg.x{SEP}Foo{SEP}bar__mutmut_1", spans, gen, src) is None


def test_resolve_survivor_line_func_not_in_source_is_none():
    name, spans, gen, _ = _method_fixture()
    assert cmg.resolve_survivor_line(name, spans, gen, "class Foo:\n    pass\n") is None


# --------------------------------------------------------------------------- #
# classify (introduced / legacy / allowlisted / fail-closed)
# --------------------------------------------------------------------------- #
def _resolver(mapping):
    def resolve(name):
        return mapping.get(name)

    return resolve


def test_classify_buckets():
    survivors = [
        ("a.x__f__mutmut_1", "survived"),
        ("a.x__g__mutmut_1", "survived"),
        ("a.x__h__mutmut_1", "survived"),
        ("a.x__k__mutmut_1", "survived"),
    ]
    changed = {"src/a.py": {10}}
    allowlist = {"a.x__k__mutmut_1"}
    resolver = _resolver(
        {
            "a.x__f__mutmut_1": ("src/a.py", 10),  # introduced
            "a.x__g__mutmut_1": ("src/a.py", 99),  # legacy
            "a.x__h__mutmut_1": None,  # fail-closed -> introduced
            "a.x__k__mutmut_1": ("src/a.py", 10),  # allowlisted (wins over location)
        }
    )
    introduced, legacy, allowlisted, fatal = cmg.classify(survivors, changed, allowlist, resolver)
    assert sorted(introduced) == ["a.x__f__mutmut_1", "a.x__h__mutmut_1"]
    assert legacy == ["a.x__g__mutmut_1"]
    assert allowlisted == ["a.x__k__mutmut_1"]
    assert fatal == []


def test_classify_fail_closed_never_legacy():
    survivors = [("a.x__f__mutmut_1", "survived")]
    introduced, legacy, _, _ = cmg.classify(survivors, {"src/a.py": {5}}, set(), _resolver({}))
    assert introduced == ["a.x__f__mutmut_1"]
    assert legacy == []


def test_classify_empty_survivors():
    assert cmg.classify([], {}, set(), _resolver({})) == ([], [], [], [])


@pytest.mark.parametrize("status", ["timeout", "suspicious", "segfault", "no tests"])
def test_classify_fatal_blocks_even_on_legacy_line(status):
    """A fatal status always lands in FATAL, never LEGACY, even if its line is
    outside the diff (which would make a `survived` mutant LEGACY)."""
    survivors = [("a.x__f__mutmut_1", status)]
    changed = {"src/a.py": {10}}  # line 99 is NOT in the diff -> would be legacy
    resolver = _resolver({"a.x__f__mutmut_1": ("src/a.py", 99)})
    introduced, legacy, allowlisted, fatal = cmg.classify(survivors, changed, set(), resolver)
    assert fatal == ["a.x__f__mutmut_1"]
    assert legacy == []
    assert introduced == []
    assert allowlisted == []


def test_classify_fatal_ignores_allowlist():
    """Allowlisting cannot rescue a fatal mutant."""
    survivors = [("a.x__f__mutmut_1", "timeout")]
    resolver = _resolver({"a.x__f__mutmut_1": ("src/a.py", 99)})
    _introduced, _legacy, allowlisted, fatal = cmg.classify(
        survivors, {}, {"a.x__f__mutmut_1"}, resolver
    )
    assert fatal == ["a.x__f__mutmut_1"]
    assert allowlisted == []


# --------------------------------------------------------------------------- #
# parse_results / load_allowlist
# --------------------------------------------------------------------------- #
def test_parse_results_filters_bad_statuses():
    text = (
        "    a.x__f__mutmut_1: survived\n"
        "    a.x__f__mutmut_2: killed\n"
        "    a.x__f__mutmut_3: timeout\n"
        "    a.x__f__mutmut_4: not checked\n"
        "    a.x__f__mutmut_5: no tests\n"
    )
    names = {n for n, _ in cmg.parse_results(text)}
    assert names == {"a.x__f__mutmut_1", "a.x__f__mutmut_3", "a.x__f__mutmut_5"}


def test_load_allowlist_ignores_comments():
    text = "# header comment\n  a.x__f__mutmut_1  # reason here\n\na.x__g__mutmut_1\n"
    assert cmg.load_allowlist(text) == {"a.x__f__mutmut_1", "a.x__g__mutmut_1"}


def test_module_has_main():
    assert callable(cmg.main)
