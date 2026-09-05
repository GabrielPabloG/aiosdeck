#!/usr/bin/env python3
"""Mutator classification for surviving mutants (hybrid heuristic + AST).

mutmut does not record *which* mutator produced a mutant. We recover it by
diffing the ``__mutmut_orig`` and ``__mutmut_<N>`` copies that live side by
side in the generated file (see ``mutation_triage``). The classifier is a pure,
deterministic function of the two function texts: no I/O, no clock, stable
ordering, so the same mutant always yields the same category.

Categories are behavior-oriented and map onto mutmut's operators
(``mutmut/mutation/mutators.py``). ``UNKNOWN`` is an explicit terminal bucket --
a mutant is never silently dropped for being hard to classify.

    MutationClassifier (Protocol)  classify(original, mutated) -> Classification
      ├── HeuristicClassifier   fast token/regex pass over the changed line
      ├── AstClassifier         libcst: exact operator/constant diff
      └── HybridClassifier      heuristic first; AST only when unsure
"""

from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

# --- categories ----------------------------------------------------------- #
RELATIONAL_OPERATOR = "RELATIONAL_OPERATOR"
BOOLEAN_OPERATOR = "BOOLEAN_OPERATOR"
ARITHMETIC_OPERATOR = "ARITHMETIC_OPERATOR"
CONDITIONAL_BOUNDARY = "CONDITIONAL_BOUNDARY"
CONSTANT_REPLACEMENT = "CONSTANT_REPLACEMENT"
STRING_MUTATION = "STRING_MUTATION"
ARG_REMOVAL = "ARG_REMOVAL"
DICT_KEYWORD = "DICT_KEYWORD"
ASSIGNMENT_TO_NONE = "ASSIGNMENT_TO_NONE"
RETURN_FLOW = "RETURN_FLOW"
MATCH_CASE_DROP = "MATCH_CASE_DROP"
UNKNOWN = "UNKNOWN"

CATEGORIES: tuple[str, ...] = (
    RELATIONAL_OPERATOR,
    BOOLEAN_OPERATOR,
    ARITHMETIC_OPERATOR,
    CONDITIONAL_BOUNDARY,
    CONSTANT_REPLACEMENT,
    STRING_MUTATION,
    ARG_REMOVAL,
    DICT_KEYWORD,
    ASSIGNMENT_TO_NONE,
    RETURN_FLOW,
    MATCH_CASE_DROP,
    UNKNOWN,
)

_COMP = {"<", "<=", ">", ">=", "==", "!="}
_BOOL_WORDS = {"and", "or"}
_IDENT_MEMBERSHIP = {"is", "is not", "in", "not in"}
_ARITH = {"+", "-", "*", "/", "//", "%", "**", "&", "|", "^", "<<", ">>"}

_COND_KW = re.compile(r"^\s*(if|elif|while|assert)\b")
_NUM = re.compile(r"^\d+$|^\d*\.\d+(?:[eE][-+]?\d+)?$")
_TOKEN = re.compile(
    r"""
    (?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<op><<=|>>=|\*\*=|//=|[-+*/%&|^<>=!~]=?|//|\*\*|<<|>>|and|or|not|is|in)
  | (?P<num>0[xX][0-9a-fA-F]+|\d+\.\d+(?:[eE][-+]?\d+)?|\d+)
  | (?P<name>[A-Za-z_]\w*)
  | (?P<delim>[(),:\[\]{}.])
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class Classification:
    """Outcome of classifying one mutant's ``original -> mutated`` change."""

    category: str
    confidence: float
    method: str  # "heuristic" | "ast" | "unknown"


class MutationClassifier(Protocol):
    def classify(self, original: str, mutated: str) -> Classification: ...


# --------------------------------------------------------------------------- #
# shared localization helpers (pure)
# --------------------------------------------------------------------------- #
def _tokens(line: str) -> list[str]:
    return [m.group() for m in _TOKEN.finditer(line)]


def _is_def(line: str) -> bool:
    s = line.strip()
    return s.startswith(("def ", "async def ")) and "__mutmut_" in s


def changed_line_pair(original: str, mutated: str) -> tuple[str, str] | None:
    """First changed (non-``def``) line pair, ignoring the rename on the ``def``.

    Returns ``(orig_line, mut_line)``; an empty side means pure insert/delete.
    ``def`` lines are filtered from both sides of a replace block so a rename
    that shares an opcode with the real mutation cannot mis-pair them.
    """
    o = original.splitlines()
    m = mutated.splitlines()
    sm = difflib.SequenceMatcher(a=o, b=m, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        oc = [o[k] for k in range(i1, i2) if not _is_def(o[k])]
        mc = [m[k] for k in range(j1, j2) if not _is_def(m[k])]
        if not oc and not mc:
            continue
        return (oc[0] if oc else "", mc[0] if mc else "")
    return None


def _line_is_condition(line: str) -> bool:
    return bool(_COND_KW.match(line)) or bool(_COMP & set(_tokens(line)))


def none_context(line: str) -> str:
    """Where a ``None`` substitution sits: ``"arg"``, ``"assign"`` or ``"other"``.

    mutmut introduces ``None`` via two operators we must not conflate:
    ``operator_arg_removal`` (``foo(x)`` -> ``foo(None)``, ``k=v`` -> ``k=None``)
    and ``operator_assignment`` (``x = expr`` -> ``x = None``). Paren/bracket
    depth at the ``None`` token plus a trailing comma tells them apart.
    """
    depth = 0
    for i, ch in enumerate(line):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif (
            line.startswith("None", i)
            and line[i - 1 : i] not in _IDENT_CHARS
            and line[i + 4 : i + 5] not in _IDENT_CHARS
        ):
            if depth > 0:
                return "arg"
            if line.rstrip().endswith(","):
                return "arg"  # keyword/positional argument fragment
            return "assign"
    return "other"


_IDENT_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


# --------------------------------------------------------------------------- #
# Heuristic classifier
# --------------------------------------------------------------------------- #
class HeuristicClassifier:
    """Classify from the token diff of the single changed line."""

    def classify(self, original: str, mutated: str) -> Classification:
        pair = changed_line_pair(original, mutated)
        if pair is None:
            return Classification(UNKNOWN, 0.0, "unknown")
        orig_line, mut_line = pair
        r, a = self._first_replace(_tokens(orig_line), _tokens(mut_line))
        return self._classify_tokens(r, a, orig_line, mut_line)

    @staticmethod
    def _first_replace(a: list[str], b: list[str]) -> tuple[list[str], list[str]]:
        sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "replace":
                return a[i1:i2], b[j1:j2]
            if tag == "delete":
                return a[i1:i2], []
            if tag == "insert":
                return [], b[j1:j2]
        return [], []

    @staticmethod
    def _classify_tokens(  # noqa: PLR0911, PLR0912 - linear operator dispatch, one rule per case
        r: list[str], a: list[str], orig_line: str, mut_line: str
    ) -> Classification:
        cond = _line_is_condition(orig_line) or _line_is_condition(mut_line)
        rs, as_ = set(r), set(a)
        if len(r) == 1 and len(a) == 1:
            ro, ao = r[0], a[0]
            if ro in _COMP or ao in _COMP:
                return Classification(RELATIONAL_OPERATOR, 0.95, "heuristic")
            if {ro, ao} <= _BOOL_WORDS:
                return Classification(BOOLEAN_OPERATOR, 0.95, "heuristic")
            if ro in _IDENT_MEMBERSHIP or ao in _IDENT_MEMBERSHIP or {ro, ao} <= _IDENT_MEMBERSHIP:
                return Classification(RELATIONAL_OPERATOR, 0.9, "heuristic")
            if ro in _ARITH or ao in _ARITH:
                return Classification(ARITHMETIC_OPERATOR, 0.9, "heuristic")
            if {ro, ao} == {"True", "False"}:
                return Classification(BOOLEAN_OPERATOR, 0.95, "heuristic")
            if "not" in (ro, ao):
                return Classification(BOOLEAN_OPERATOR, 0.85, "heuristic")
            if _NUM.match(ro) and _NUM.match(ao):
                cat = CONDITIONAL_BOUNDARY if cond else CONSTANT_REPLACEMENT
                return Classification(cat, 0.8, "heuristic")
            if _is_str(ro) and _is_str(ao):
                return Classification(STRING_MUTATION, 0.9, "heuristic")
        if "None" in as_ or "None" in rs:
            ctx = none_context(mut_line if "None" in as_ else orig_line)
            if ctx == "arg":
                return Classification(ARG_REMOVAL, 0.8, "heuristic")
            if ctx == "assign":
                return Classification(ASSIGNMENT_TO_NONE, 0.85, "heuristic")
        if any("XX" in t for t in a):
            if "=" in mut_line and any(t.endswith("XX=") or t == "XX" for t in a):
                return Classification(DICT_KEYWORD, 0.55, "heuristic")
            return Classification(STRING_MUTATION, 0.85, "heuristic")
        if rs & {"break", "continue", "return"} or as_ & {"break", "continue", "return"}:
            return Classification(RETURN_FLOW, 0.8, "heuristic")
        if not a and r:
            return Classification(ARG_REMOVAL, 0.55, "heuristic")
        if any(_NUM.match(t) for t in r) and any(_NUM.match(t) for t in a):
            cat = CONDITIONAL_BOUNDARY if cond else CONSTANT_REPLACEMENT
            return Classification(cat, 0.6, "heuristic")
        return Classification(UNKNOWN, 0.0, "unknown")


def _is_str(tok: str) -> bool:
    return len(tok) >= 2 and tok[0] in "\"'" and tok[-1] == tok[0]  # noqa: PLR2004


# --------------------------------------------------------------------------- #
# AST classifier (libcst) -- exact for operator / constant swaps
# --------------------------------------------------------------------------- #
def _parse_line(line: str):
    """Parse a possibly-indented / fragment line into a libcst module.

    Tries the bare statement, then wraps it in a dummy ``def`` / ``if`` / ``for``
    body so lines like ``return x < 1`` (invalid at module scope) still parse.
    Returns ``None`` if nothing parses (e.g. a dict-entry fragment).
    """
    import libcst as cst  # noqa: PLC0415 - lazy: heuristic-only runs need no libcst

    s = line.strip()
    if not s:
        return None
    for candidate in (s, f"def _():\n    {s}", f"if True:\n    {s}", f"for _ in ():\n    {s}"):
        try:
            return cst.parse_module(candidate + "\n")
        except Exception:  # noqa: BLE001 - try the next wrapper
            continue
    return None


def _ast_features(line: str) -> Counter[str]:
    """Fine-grained feature multiset for a line (operator symbols, constants)."""
    import libcst as cst  # noqa: PLC0415 - lazy: only the AST escalation needs libcst

    symbol = {
        cst.LessThan: "<",
        cst.LessThanEqual: "<=",
        cst.GreaterThan: ">",
        cst.GreaterThanEqual: ">=",
        cst.Equal: "==",
        cst.NotEqual: "!=",
        cst.Is: "is",
        cst.IsNot: "is not",
        cst.In: "in",
        cst.NotIn: "not in",
        cst.Plus: "+",
        cst.Minus: "-",
        cst.Add: "+",
        cst.Subtract: "-",
        cst.Multiply: "*",
        cst.Divide: "/",
        cst.FloorDivide: "//",
        cst.Modulo: "%",
        cst.Power: "**",
        cst.BitAnd: "&",
        cst.BitOr: "|",
        cst.BitXor: "^",
        cst.LeftShift: "<<",
        cst.RightShift: ">>",
        cst.And: "and",
        cst.Or: "or",
        cst.Not: "not",
        cst.BitInvert: "~",
    }
    feats: Counter[str] = Counter()
    module = _parse_line(line)
    if module is None:
        return feats

    class V(cst.CSTVisitor):
        def visit_BinaryOperation(self, node: cst.BinaryOperation) -> None:  # noqa: N802
            feats[f"BIN:{symbol.get(type(node.operator), '?')}"] += 1

        def visit_BooleanOperation(self, node: cst.BooleanOperation) -> None:  # noqa: N802
            feats[f"BOOL:{symbol.get(type(node.operator), '?')}"] += 1

        def visit_UnaryOperation(self, node: cst.UnaryOperation) -> None:  # noqa: N802
            feats[f"UNARY:{symbol.get(type(node.operator), '?')}"] += 1

        def visit_Comparison(self, node: cst.Comparison) -> None:  # noqa: N802
            for comp in node.comparisons:
                feats[f"CMP:{symbol.get(type(comp.operator), '?')}"] += 1

        def visit_Integer(self, node: cst.Integer) -> None:  # noqa: N802
            feats[f"NUM:{node.value}"] += 1

        def visit_Float(self, node: cst.Float) -> None:  # noqa: N802
            feats[f"NUM:{node.value}"] += 1

        def visit_SimpleString(self, node: cst.SimpleString) -> None:  # noqa: N802
            feats[f"STR:{node.value}"] += 1

        def visit_Name(self, node: cst.Name) -> None:  # noqa: N802
            if node.value in {"True", "False", "None"}:
                feats[f"NAME:{node.value}"] += 1

    module.visit(V())
    return feats


class AstClassifier:
    """Recover the exact category by diffing libcst feature multisets."""

    def classify(self, original: str, mutated: str) -> Classification:
        pair = changed_line_pair(original, mutated)
        if pair is None:
            return Classification(UNKNOWN, 0.0, "unknown")
        orig_line, mut_line = pair
        removed, added = _diff_features(_ast_features(orig_line), _ast_features(mut_line))
        cond = _line_is_condition(orig_line) or _line_is_condition(mut_line)
        return _category_from_features(removed, added, cond)


def _diff_features(a: Counter[str], b: Counter[str]) -> tuple[set[str], set[str]]:
    removed = {k for k in a if a[k] > b.get(k, 0)}
    added = {k for k in b if b[k] > a.get(k, 0)}
    return removed, added


def _category_from_features(  # noqa: PLR0911 - one guard per feature family
    removed: set[str], added: set[str], cond: bool
) -> Classification:
    fams = {k.split(":", 1)[0] for k in removed | added}
    if not fams or fams == {""}:
        return Classification(UNKNOWN, 0.0, "unknown")
    if fams <= {"CMP"}:
        return Classification(RELATIONAL_OPERATOR, 1.0, "ast")
    if fams <= {"BOOL"} or fams <= {"UNARY"}:
        return Classification(BOOLEAN_OPERATOR, 1.0, "ast")
    if fams <= {"BIN"}:
        return Classification(ARITHMETIC_OPERATOR, 1.0, "ast")
    if fams <= {"NAME"}:
        if any(k == "NAME:None" for k in removed | added):
            return Classification(ASSIGNMENT_TO_NONE, 0.9, "ast")
        return Classification(BOOLEAN_OPERATOR, 1.0, "ast")  # True<->False
    if fams <= {"STR"}:
        return Classification(STRING_MUTATION, 1.0, "ast")
    if fams <= {"NUM"}:
        cat = CONDITIONAL_BOUNDARY if cond else CONSTANT_REPLACEMENT
        return Classification(cat, 1.0, "ast")
    return Classification(UNKNOWN, 0.3, "unknown")  # mixed families -> ambiguous


# --------------------------------------------------------------------------- #
# Hybrid
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class HybridClassifier:
    """Heuristic first; escalate to AST when the heuristic is unsure."""

    min_confidence: float = 0.8
    heuristic: MutationClassifier = HeuristicClassifier()
    ast: MutationClassifier = AstClassifier()

    def classify(self, original: str, mutated: str) -> Classification:
        h = self.heuristic.classify(original, mutated)
        if h.confidence >= self.min_confidence:
            return h
        a = self.ast.classify(original, mutated)
        return a if a.confidence > h.confidence else h
