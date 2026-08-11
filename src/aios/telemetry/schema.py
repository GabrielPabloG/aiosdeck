"""Versioned benchmark schema — canonical report envelope and validation.

``results[]`` is the single canonical representation of benchmark output.
Every measurement pipeline emits one flat list of results; no parallel
``phases``/``commands``/``startup`` structures survive at the top level of a
report. This module owns the schema constants and a hand-rolled,
zero-dependency validator so any tool can check a report offline.
"""

from __future__ import annotations

import platform
import subprocess
import sys

SCHEMA_VERSION = "1.0"
REQUIRED_KEYS = (
    "schema_version",
    "aiosdeck_version",
    "git_commit",
    "timestamp",
    "system_info",
    "results",
)
METRICS = ("wall_time_ms", "cpu_user_ms", "cpu_system_ms", "peak_memory_kb")
GROUPS = ("phases", "commands", "startup")


def validate_report(report: dict) -> list[str]:
    """Return a list of schema violations; an empty list means valid.

    Checks the envelope (required keys, schema version), that ``results`` is a
    list, and that every result carries a known ``group``/``target`` plus
    either a skipped marker or non-empty ``runs`` whose metrics are exactly
    ``METRICS``.
    """
    errors: list[str] = []

    for key in REQUIRED_KEYS:
        if key not in report:
            errors.append(f"missing top-level key: {key}")

    if "schema_version" in report and report["schema_version"] != SCHEMA_VERSION:
        errors.append(f"schema_version {report['schema_version']!r} != expected {SCHEMA_VERSION!r}")

    if "results" not in report:
        return errors
    if not isinstance(report["results"], list):
        errors.append("results must be a list")
        return errors

    for i, result in enumerate(report["results"]):
        _validate_result(errors, i, result)
    return errors


def _validate_result(errors: list[str], index: int, result: object) -> None:
    if not isinstance(result, dict):
        errors.append(f"results[{index}] must be an object")
        return
    if result.get("group") not in GROUPS:
        errors.append(f"results[{index}] group must be one of {', '.join(GROUPS)}")
    if "target" not in result:
        errors.append(f"results[{index}] missing target")
    if result.get("skipped"):
        if not result.get("reason"):
            errors.append(f"results[{index}] skipped result missing reason")
        return
    runs = result.get("runs")
    if not isinstance(runs, list) or not runs:
        errors.append(f"results[{index}] must have a non-empty runs list")
        return
    if "summaries" not in result:
        errors.append(f"results[{index}] missing summaries")
    for j, run in enumerate(runs):
        _validate_run(errors, index, j, run)


def _validate_run(errors: list[str], index: int, run_index: int, run: object) -> None:
    label = f"results[{index}].runs[{run_index}]"
    if not isinstance(run, dict):
        errors.append(f"{label} must be an object")
        return
    for metric in METRICS:
        if metric not in run:
            errors.append(f"{label} missing metric {metric}")
    for key in run:
        if key not in METRICS and key != "error":
            errors.append(f"{label} unknown key {key!r}")


def system_info() -> dict:
    """Local platform snapshot for report provenance (zero external deps)."""
    return {
        "system": platform.system(),
        "platform": sys.platform,
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "python": platform.python_version(),
    }


def git_commit() -> str:
    """Short HEAD commit hash, or ``"unknown"`` when git is unavailable."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "unknown"
    return proc.stdout.strip() or "unknown"
