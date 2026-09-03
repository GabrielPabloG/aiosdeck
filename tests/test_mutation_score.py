"""Unit tests for the fair mutation-score gate (.pre-commit/mutation_score.py).

All inputs are synthetic ``mutmut results --all=true`` text, so the algorithm
is validated without running mutmut.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _locate_script() -> Path:
    """Find the script by climbing ancestors, so it resolves both under plain
    pytest (``<repo>/tests/...``) and when mutmut runs the suite from a copied
    tree (``<repo>/mutants/tests/...``) where ``.pre-commit/`` is not staged
    next to the test. Returns the first ancestor that actually has it.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / ".pre-commit" / "mutation_score.py"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("could not locate .pre-commit/mutation_score.py")


_SPEC_PATH = _locate_script()
_spec = importlib.util.spec_from_file_location("mutation_score", _SPEC_PATH)
assert _spec is not None and _spec.loader is not None
ms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ms)


# --------------------------------------------------------------------------- #
# func_key
# --------------------------------------------------------------------------- #
def test_func_key_strips_index():
    name = "aios.workflow.engine.x__Foo__bar__mutmut_42"
    assert ms.func_key(name) == "aios.workflow.engine.x__Foo__bar"


def test_func_key_no_index_is_unchanged():
    assert ms.func_key("aios.config.loader.x__f") == "aios.config.loader.x__f"


# --------------------------------------------------------------------------- #
# load_allowlist
# --------------------------------------------------------------------------- #
def test_load_allowlist_ignores_comments_and_blanks():
    text = "# header\n  a.x__f__mutmut_1  # reason\n\n\na.x__g__mutmut_1\n"
    assert ms.load_allowlist(text) == {"a.x__f__mutmut_1", "a.x__g__mutmut_1"}


def test_load_allowlist_empty():
    assert ms.load_allowlist("") == set()


# --------------------------------------------------------------------------- #
# parse_all_results
# --------------------------------------------------------------------------- #
def test_parse_all_results_keeps_every_status():
    text = (
        "    a.x__f__mutmut_1: survived\n"
        "    a.x__f__mutmut_2: killed\n"
        "    a.x__f__mutmut_3: not checked\n"
        "    a.x__f__mutmut_4: no tests\n"
        "    a.x__f__mutmut_5: timeout\n"
    )
    parsed = ms.parse_all_results(text)
    assert parsed == {
        "a.x__f__mutmut_1": "survived",
        "a.x__f__mutmut_2": "killed",
        "a.x__f__mutmut_3": "not checked",
        "a.x__f__mutmut_4": "no tests",
        "a.x__f__mutmut_5": "timeout",
    }


def test_parse_all_results_status_with_space():
    parsed = ms.parse_all_results("m.x__f__mutmut_9: not checked")
    assert parsed["m.x__f__mutmut_9"] == "not checked"


def test_parse_all_results_skips_non_result_lines():
    # lines without ": " are dropped; a value splits on the LAST ": "
    parsed = ms.parse_all_results("Mutant results\n\n  a: b: c\nnothing here")
    assert parsed == {"a: b": "c"}


# --------------------------------------------------------------------------- #
# count_status / allowlisted_survivors
# --------------------------------------------------------------------------- #
def test_count_status():
    parsed = {"a": "survived", "b": "not checked", "c": "not checked"}
    assert sorted(ms.count_status(parsed, "not checked")) == ["b", "c"]


def test_allowlisted_survivors_only_counts_surviving_names():
    parsed = {
        "a.x__f__mutmut_1": "survived",
        "a.x__f__mutmut_2": "killed",  # in allowlist but killed -> must NOT count
    }
    allowlist = {"a.x__f__mutmut_1", "a.x__f__mutmut_2"}
    assert ms.allowlisted_survivors(parsed, allowlist) == ["a.x__f__mutmut_1"]


# --------------------------------------------------------------------------- #
# compute_fair_score
# --------------------------------------------------------------------------- #
def test_compute_fair_score_excludes_allowlisted():
    # killed 14857, survived 10307, 19 allowlisted -> 14857/25145 -> 59%
    score, denom = ms.compute_fair_score(14857, 10307, 19)
    assert denom == 25145
    assert score == 14857 * 100 // 25145 == 59


def test_compute_fair_score_is_floor_division():
    score, denom = ms.compute_fair_score(2, 1, 0)
    assert (score, denom) == (66, 3)  # 2/3 -> 66%, not 67%


def test_compute_fair_score_zero_denominator_is_zero():
    assert ms.compute_fair_score(0, 0, 0) == (0, 0)
    assert ms.compute_fair_score(5, 5, 10) == (0, 0)  # allowlisted clipped upstream


# --------------------------------------------------------------------------- #
# triage_by_function
# --------------------------------------------------------------------------- #
def test_triage_groups_by_function_and_ranks_by_killable():
    parsed = {
        "mod.x__big__mutmut_1": "survived",
        "mod.x__big__mutmut_2": "survived",
        "mod.x__small__mutmut_1": "survived",
        "mod.x__killed__mutmut_1": "killed",
    }
    rows = ms.triage_by_function(parsed, "survived", ())
    assert rows == [("mod.x__big", 2, 2), ("mod.x__small", 1, 1)]


def test_triage_subtracts_allowlisted_from_killable():
    parsed = {
        "mod.x__f__mutmut_1": "survived",
        "mod.x__f__mutmut_2": "survived",
    }
    rows = ms.triage_by_function(parsed, "survived", {"mod.x__f__mutmut_1"})
    assert rows == [("mod.x__f", 2, 1)]  # total 2, killable 1


def test_triage_empty_when_no_survivors():
    assert ms.triage_by_function({"a": "killed"}, "survived", ()) == []


def test_module_has_main():
    assert callable(ms.main)
