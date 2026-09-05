"""Unit tests for the mutation classifier (.pre-commit/mutation_classifier.py).

All inputs are synthetic ``def``/mutant function texts, so classification is
validated without mutmut. The AST classifier needs libcst (a mutmut dependency);
those tests skip if it is somehow unavailable.
"""

from __future__ import annotations

import importlib.util
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


_spec = importlib.util.spec_from_file_location(
    "mutation_classifier", _locate("mutation_classifier.py")
)
assert _spec is not None and _spec.loader is not None
mc = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mc
_spec.loader.exec_module(mc)


def _fn(body_orig: str, body_mut: str) -> tuple[str, str]:
    return f"def f(x, y):\n{body_orig}", f"def f(x, y):\n{body_mut}"


# --------------------------------------------------------------------------- #
# none_context
# --------------------------------------------------------------------------- #
def test_none_context_arg_vs_assign():
    assert mc.none_context("    return foo(None)") == "arg"
    assert mc.none_context("    x = None") == "assign"
    assert mc.none_context("    title=None,") == "arg"  # keyword-arg fragment
    assert mc.none_context("    x = 1") == "other"


def test_none_context_ignores_none_in_word():
    assert mc.none_context("    x = NoneType()") == "other"


# --------------------------------------------------------------------------- #
# changed_line_pair
# --------------------------------------------------------------------------- #
def test_changed_line_pair_skips_def_rename():
    orig, mut = _fn("    return x < 1", "    return x <= 1")
    pair = mc.changed_line_pair(orig, mut)
    assert pair == ("    return x < 1", "    return x <= 1")


def test_changed_line_pair_none_when_only_def_differs():
    orig = "def f__mutmut_orig(x):\n    return x"
    mut = "def f__mutmut_1(x):\n    return x"
    assert mc.changed_line_pair(orig, mut) is None


# --------------------------------------------------------------------------- #
# HeuristicClassifier
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("body_orig", "body_mut", "expected"),
    [
        ("    return x < y", "    return x <= y", mc.RELATIONAL_OPERATOR),
        ("    return x and y", "    return x or y", mc.BOOLEAN_OPERATOR),
        ("    flag = True", "    flag = False", mc.BOOLEAN_OPERATOR),
        ("    return x + y", "    return x - y", mc.ARITHMETIC_OPERATOR),
        ('    s = "low"', '    s = "XXlowXX"', mc.STRING_MUTATION),
        ("    z = compute()", "    z = None", mc.ASSIGNMENT_TO_NONE),
        ("    return foo(x)", "    return foo(None)", mc.ARG_REMOVAL),
        ("    for i in x:\n        break", "    for i in x:\n        return", mc.RETURN_FLOW),
    ],
)
def test_heuristic_categories(body_orig, body_mut, expected):
    orig, mut = _fn(body_orig, body_mut)
    result = mc.HeuristicClassifier().classify(orig, mut)
    assert result.category == expected
    assert result.confidence >= 0.8


def test_heuristic_conditional_boundary_vs_constant():
    cond = mc.HeuristicClassifier().classify(*_fn("    if x > 5:", "    if x > 6:"))
    plain = mc.HeuristicClassifier().classify(*_fn("    return 5", "    return 6"))
    assert cond.category == mc.CONDITIONAL_BOUNDARY
    assert plain.category == mc.CONSTANT_REPLACEMENT


def test_heuristic_unknown_on_punctuation_only():
    orig, mut = _fn("    z = (1)", "    z = [1]")
    assert mc.HeuristicClassifier().classify(orig, mut).category == mc.UNKNOWN


# --------------------------------------------------------------------------- #
# AstClassifier (libcst)
# --------------------------------------------------------------------------- #
pytest.importorskip("libcst")


@pytest.mark.parametrize(
    ("body_orig", "body_mut", "expected"),
    [
        ("    return x < y", "    return x <= y", mc.RELATIONAL_OPERATOR),
        ("    return x and y", "    return x or y", mc.BOOLEAN_OPERATOR),
        ("    return x + y", "    return x - y", mc.ARITHMETIC_OPERATOR),
        ('    s = "low"', '    s = "up"', mc.STRING_MUTATION),
        ("    return 5", "    return 6", mc.CONSTANT_REPLACEMENT),
    ],
)
def test_ast_exact_categories(body_orig, body_mut, expected):
    result = mc.AstClassifier().classify(*_fn(body_orig, body_mut))
    assert result.category == expected
    assert result.confidence == 1.0
    assert result.method == "ast"


def test_ast_graceful_on_unparseable_fragment():
    # changed line is a dict-entry fragment -> libcst cannot parse it
    orig, mut = _fn('    "a": 1,', '    "a": 2,')
    assert mc.AstClassifier().classify(orig, mut).category == mc.UNKNOWN


# --------------------------------------------------------------------------- #
# HybridClassifier
# --------------------------------------------------------------------------- #
class _Stub:
    def __init__(self, category, confidence):
        self._c = mc.Classification(category, confidence, "stub")

    def classify(self, original, mutated):
        return self._c


def test_hybrid_accepts_confident_heuristic():
    hyb = mc.HybridClassifier(
        min_confidence=0.8, heuristic=_Stub(mc.UNKNOWN, 0.95), ast=_Stub("X", 1.0)
    )
    assert hyb.classify("a", "b").category == mc.UNKNOWN  # heuristic conf >= min wins


def test_hybrid_escalates_to_ast_on_low_confidence():
    hyb = mc.HybridClassifier(
        min_confidence=0.8,
        heuristic=_Stub(mc.UNKNOWN, 0.3),
        ast=_Stub(mc.RELATIONAL_OPERATOR, 1.0),
    )
    result = hyb.classify("a", "b")
    assert result.category == mc.RELATIONAL_OPERATOR
    assert result.method == "stub"


def test_hybrid_real_end_to_end():
    hyb = mc.HybridClassifier()
    assert (
        hyb.classify(*_fn("    return x < y", "    return x <= y")).category
        == mc.RELATIONAL_OPERATOR
    )
