#!/usr/bin/env python3
"""Mutation-score gate + survivor triage for the nightly job.

The nightly judges test quality with a *fair* kill-rate that isolates real
assertion weakness:

    score = killed / (killed + survived - allowlisted_equivalents)

``no tests`` mutants (uncovered code) and ``timeout``/``skipped`` are excluded
from the denominator: they are separate signals (coverage / infra), not proof
of a weak assertion. Only mutants that were actually executed and *survived*
count against the score, minus provably-equivalent survivors listed in the
allowlist (unkillable by definition, so they must not cap a reachable score).

Fail-closed on an incomplete run: if any mutant is ``not checked`` the run did
not finish and the score is meaningless, so the gate fails outright.

It also prints a triage report -- survivors grouped by function and ranked --
so the follow-up work (writing tests) targets the biggest holes first. Pure
functions take text arguments (no I/O) and are unit-tested; only ``main``
shells out to mutmut.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path

SURVIVED = "survived"
NOT_CHECKED = "not checked"
NO_TESTS = "no tests"

# A mutant name is ``<module>.<span_key>__mutmut_<N>``; the function key drops
# the trailing index so all mutants of one function group together.
_MUTANT_INDEX = re.compile(r"__mutmut_\d+$")


def func_key(name: str) -> str:
    """Strip the ``__mutmut_<N>`` suffix, yielding the owning function key."""
    return _MUTANT_INDEX.sub("", name)


def load_allowlist(text: str) -> set[str]:
    """Read the equivalents allowlist: ``<name>  # reason`` lines, ignoring comments."""
    allowed: set[str] = set()
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            allowed.add(line)
    return allowed


def parse_all_results(results_text: str) -> dict[str, str]:
    """Map every mutant ``name -> status`` from ``mutmut results --all=true`` output.

    Names never contain ``": "``; statuses may contain spaces (``not checked``,
    ``no tests``), so split on the last ``": "`` only.
    """
    status_by_name: dict[str, str] = {}
    for raw in results_text.splitlines():
        line = raw.strip()
        if ": " not in line:
            continue
        name, status = line.rsplit(": ", 1)
        status_by_name[name.strip()] = status.strip()
    return status_by_name


def count_status(status_by_name: Mapping[str, str], status: str) -> list[str]:
    """Names whose parsed status equals ``status``."""
    return [name for name, got in status_by_name.items() if got == status]


def allowlisted_survivors(
    status_by_name: Mapping[str, str], allowlist: set[str]
) -> list[str]:
    """Survivors that are provably equivalent (named in the allowlist)."""
    return [
        name
        for name, status in status_by_name.items()
        if status == SURVIVED and name in allowlist
    ]


def compute_fair_score(
    killed: int, survived: int, allowlisted: int
) -> tuple[int, int]:
    """Return ``(score_percent, denominator)`` for the fair kill-rate.

    ``allowlisted`` must already be clipped to ``survived`` by the caller.
    A non-positive denominator (nothing killable) yields a 0 score, which the
    gate treats as a failure rather than a vacuous pass.
    """
    denom = killed + survived - allowlisted
    if denom <= 0:
        return 0, denom
    return killed * 100 // denom, denom


def triage_by_function(
    status_by_name: Mapping[str, str], status: str, allowlist: Iterable[str]
) -> list[tuple[str, int, int]]:
    """Rank functions by surviving mutants of ``status``.

    Returns ``[(func_key, total, killable), ...]`` sorted by killable desc, then
    total desc, then name. ``killable`` subtracts allowlisted equivalents.
    """
    allowed = set(allowlist)
    rows: dict[str, list[int]] = {}
    for name, got in status_by_name.items():
        if got != status:
            continue
        key = func_key(name)
        total, killable = rows.get(key, [0, 0])
        rows[key] = [total + 1, killable + (0 if name in allowed else 1)]
    ordered = sorted(rows.items(), key=lambda kv: (-kv[1][1], -kv[1][0], kv[0]))
    return [(key, total, killable) for key, (total, killable) in ordered]


# --------------------------------------------------------------------------- #
# I/O glue (only main touches the filesystem / subprocesses)
# --------------------------------------------------------------------------- #
def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _run_mutmut_results(repo_root: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["mutmut", "results", "--all=true"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def _print_triage(title: str, rows: list[tuple[str, int, int]], limit: int) -> None:
    print(f"\n--- {title} (top {limit}) ---")
    if not rows:
        print("  (none)")
        return
    for key, total, killable in rows[:limit]:
        note = "" if killable == total else f"  [{total - killable} allowlisted]"
        print(f"  {killable:>5} killable / {total:>5}  {key}{note}")


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0912 - linear CLI glue
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", type=Path)
    parser.add_argument("--stats", default="mutants/mutmut-cicd-stats.json", type=Path)
    parser.add_argument("--allowlist", default=".github/mutmut-equivalents.txt", type=Path)
    parser.add_argument("--threshold", default=80, type=int)
    parser.add_argument("--limit", default=20, type=int, help="rows per triage table")
    parser.add_argument(
        "--results-file", default=None, type=Path,
        help="read `mutmut results --all=true` output from a file instead of shelling out",
    )
    args = parser.parse_args(argv)

    repo_root: Path = args.repo_root
    stats_path = args.stats if args.stats.is_absolute() else repo_root / args.stats
    allowlist_path = args.allowlist if args.allowlist.is_absolute() else repo_root / args.allowlist

    stats_text = _read(stats_path)
    if stats_text is None:
        print(f"ERROR: cannot read stats at {stats_path}", file=sys.stderr)
        return 1
    stats = json.loads(stats_text)

    if args.results_file is not None:
        rf = args.results_file if args.results_file.is_absolute() else repo_root / args.results_file
        results_text = _read(rf)
    else:
        results_text = _run_mutmut_results(repo_root)
    if not results_text:
        print("ERROR: no `mutmut results` output; run is incomplete or mutmut missing", file=sys.stderr)
        return 1

    status_by_name = parse_all_results(results_text)
    allowlist = load_allowlist(_read(allowlist_path) or "")

    not_checked = count_status(status_by_name, NOT_CHECKED)
    if not_checked:
        print(
            f"FAIL: run incomplete -- {len(not_checked)} mutant(s) 'not checked'. "
            "Finish `mutmut run` before scoring.",
            file=sys.stderr,
        )
        for key, _total, _killable in triage_by_function(
            {n: NOT_CHECKED for n in not_checked}, NOT_CHECKED, ()
        )[: args.limit]:
            print(f"  not checked: {key}", file=sys.stderr)
        return 1

    allowlisted = allowlisted_survivors(status_by_name, allowlist)
    killed = int(stats.get("killed", 0))
    survived = int(stats.get("survived", 0))
    score, denom = compute_fair_score(killed, survived, min(len(allowlisted), survived))

    survivors = count_status(status_by_name, SURVIVED)
    if len(survivors) != survived:
        print(
            f"WARNING: results list {len(survivors)} survivors but stats says {survived}",
            file=sys.stderr,
        )

    print(
        f"Mutation score (fair): {score}% ({killed}/{denom}) "
        f"[threshold {args.threshold}%]"
    )
    print(
        f"  survived={survived}  allowlisted_equivalents={len(allowlisted)}  "
        f"no_tests={stats.get('no_tests', 0)}  timeout={stats.get('timeout', 0)}"
    )
    _print_triage(
        "survivor triage", triage_by_function(status_by_name, SURVIVED, allowlist), args.limit
    )
    _print_triage(
        "no-tests triage", triage_by_function(status_by_name, NO_TESTS, ()), args.limit
    )

    if score < args.threshold:
        print(f"FAIL: fair mutation score {score}% below {args.threshold}% threshold.", file=sys.stderr)
        return 1
    print("PASS: fair mutation score meets threshold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
