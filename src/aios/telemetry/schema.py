"""Versioned benchmark schema — canonical report envelope and validation.

``results[]`` is the single canonical representation of benchmark output.
Every measurement pipeline emits one flat list of results; no parallel
``phases``/``commands``/``startup`` structures survive at the top level of a
report. This module owns the schema constants and a hand-rolled,
zero-dependency validator so any tool can check a report offline.

Mode is metadata, never a metric: since v1.1 a report may carry
``benchmark_mode`` (``"full"``/``"bare"``) and ``task_prompt_type``
(``"full_task"``/``"restricted_ok"``) on the envelope, and results may carry
result-level extras such as ``tool_calls_count``, ``is_read_only``, ``model``
(the effective routing decision for a phase), and ``warnings``. Per-run
metrics stay exactly ``METRICS`` (plus optional ``error``/``timings``);
nothing else is allowed inside a run.
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
from pathlib import Path

SCHEMA_VERSION = "1.1"
SUPPORTED_SCHEMA_VERSIONS = ("1.0", "1.1")
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
    ``METRICS``. Since v1.1 a run may carry an optional ``timings`` breakdown
    (``kernel.timings`` contract); 1.0 reports remain valid. Result-level keys
    beyond ``group``/``target``/``runs``/``summaries``/``skipped``/``reason``
    (e.g. bare-mode ``tool_calls_count``, ``is_read_only``, ``warnings``) are
    accepted — the run-level metrics are the closed set.
    """
    errors: list[str] = []

    for key in REQUIRED_KEYS:
        if key not in report:
            errors.append(f"missing top-level key: {key}")

    if "schema_version" in report and report["schema_version"] not in SUPPORTED_SCHEMA_VERSIONS:
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
        if key not in METRICS and key not in ("error", "timings"):
            errors.append(f"{label} unknown key {key!r}")
    timings = run.get("timings")
    if timings is not None and not isinstance(timings, dict):
        errors.append(f"{label} timings must be an object")


def system_info() -> dict:
    """Local platform snapshot for report provenance (zero external deps).

    The enriched fields — distro, kernel, cpu, cpu_count, memory_mb — let a
    baseline explain the environment that produced it, so future comparisons
    can tell hardware drift apart from real regressions. Hardware is recorded
    as context, not as an identity requirement.
    """
    return {
        "system": platform.system(),
        "platform": sys.platform,
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "python": platform.python_version(),
        "distro": _distro(),
        "kernel": platform.release(),
        "cpu": _cpu_model(),
        "cpu_count": _cpu_count(),
        "memory_mb": _memory_mb(),
    }


def _distro() -> str:
    """OS distribution name/version from /etc/os-release, else platform()."""
    try:
        release = Path("/etc/os-release").read_text(encoding="utf-8")
        fields = dict(line.split("=", 1) for line in release.splitlines() if "=" in line)
        name = fields.get("NAME", "").strip('"')
        version = fields.get("VERSION_ID", "").strip('"')
        return f"{name} {version}".strip()
    except OSError:
        return platform.platform()


def _cpu_model() -> str:
    """Human-readable CPU model, falling back to platform.machine()."""
    processor = platform.processor()
    if processor:
        return processor
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.machine()


def _cpu_count() -> int:
    """Available logical CPUs, preferring the process affinity mask."""
    try:
        return len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return os.cpu_count() or 0


def _memory_mb() -> int:
    """Total physical memory in MB via /proc/meminfo (0 when unavailable)."""
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal"):
                return int(re.split(r"\s+", line)[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


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
