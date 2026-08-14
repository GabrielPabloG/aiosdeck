"""Benchmark comparison logic (#59) — pure, no CLI imports.

Consumes existing benchmark reports (``load_report``) and their summaries
(``summarize_runs``); it never measures, never classifies metrics the schema
does not own, and never forked the schema — GROUPS/METRICS stay closed in
``aios.telemetry.schema``.

Categories:
- ``runtime`` (corroborative, environment/model dependent): (phases, plan),
  (phases, agent_exec), (commands, plan), (commands, backlog).
- ``core`` (committable): every other (group, target).

Targets are matched by ``(group, target)`` using ``summaries.wall_time_ms``.
A target absent from either side is ``skipped`` — never a regression.
``delta_pct`` is reported per p50/p95/p99 (percentiles already available in
each summary); the gate is p50 against ``--threshold`` (default 10).

Exit-code contract (precedence 2 > 1 > 0):
- 0 — no Core regression, environment compatible
- 1 — Core regression above threshold
- 2 — environment/runtime divergence (system_info cpu_count/cpu/distro/kernel/
  python and/or runtime_info provider/model/host). A regression measured in an
  incompatible environment is never reported as real.

``compare_reports`` returns a *valid benchmark report*: envelope from the
current report, ``results[]`` reusing each target's original group with the
current runs, plus result-level extras (baseline_p50_ms, current_p50_ms,
delta_pct, verdict, category) and a top-level ``compare`` key.
"""

from __future__ import annotations

from aios.telemetry.benchmark import summarize_runs

DEFAULT_THRESHOLD_PCT = 10.0

RUNTIME_DEPENDENT = frozenset(
    {
        ("phases", "plan"),
        ("phases", "agent_exec"),
        ("commands", "plan"),
        ("commands", "backlog"),
    }
)

ENV_KEYS = ("cpu", "cpu_count", "distro", "kernel", "python")
RUNTIME_KEYS = ("provider", "model", "host")


def category_for(group: str, target: str) -> str:
    """Classify a matched target as ``core`` or ``runtime``."""
    return "runtime" if (group, target) in RUNTIME_DEPENDENT else "core"


def _differ(left: dict | None, right: dict | None, keys: tuple[str, ...]) -> list[str]:
    left = left or {}
    right = right or {}
    return sorted(key for key in keys if left.get(key) != right.get(key))


def env_divergence(baseline: dict, current: dict) -> list[str]:
    """system_info fields that differ between reports (empty means compatible)."""
    return _differ(baseline.get("system_info"), current.get("system_info"), ENV_KEYS)


def runtime_divergence(baseline: dict, current: dict) -> list[str]:
    """runtime_info fields that differ (provider/model/host)."""
    return _differ(baseline.get("runtime_info"), current.get("runtime_info"), RUNTIME_KEYS)


def _wall_p50(result: dict | None) -> float | None:
    if result is None or result.get("skipped"):
        return None
    summary = (result.get("summaries") or {}).get("wall_time_ms")
    if not summary:
        return None
    p50 = summary.get("p50")
    return p50 if isinstance(p50, (int, float)) else None


def compare_reports(
    baseline: dict,
    current: dict,
    threshold: float = DEFAULT_THRESHOLD_PCT,
    *,
    live: bool = False,
) -> dict:
    """Compare ``baseline`` against ``current`` and return a valid report.

    The returned envelope is ``current`` with ``results`` rebuilt so that every
    original target keeps its group and the current runs/summaries, augmented
    with comparison extras. A top-level ``compare`` key carries the summary and
    the computed ``exit_code``.
    """
    baseline_by_key = {(r["group"], r["target"]): r for r in baseline.get("results", [])}
    current_by_key = {(r["group"], r["target"]): r for r in current.get("results", [])}
    keys = sorted(set(baseline_by_key) | set(current_by_key))

    report = dict(current)
    report["results"] = []

    skipped: list[dict] = []
    core_regressions: list[dict] = []
    runtime_warnings: list[dict] = []

    for key in keys:
        group, target = key
        category = category_for(group, target)
        baseline_result = baseline_by_key.get(key)
        current_result = current_by_key.get(key)

        baseline_p50 = _wall_p50(baseline_result)
        current_p50 = _wall_p50(current_result)

        if baseline_p50 is None or current_p50 is None:
            reason = (
                "not measured in baseline" if current_p50 is not None else "not measured in current"
            )
            skipped.append({"group": group, "target": target, "reason": reason})
            report["results"].append(
                {
                    "group": group,
                    "target": target,
                    "category": category,
                    "verdict": "skipped",
                    "skipped": True,
                    "reason": reason,
                }
            )
            continue

        delta_pct = (current_p50 - baseline_p50) / baseline_p50 * 100.0
        if delta_pct > threshold:
            if category == "core":
                verdict = "regression"
                core_regressions.append({"group": group, "target": target, "delta_pct": delta_pct})
            else:
                verdict = "warning"
                runtime_warnings.append({"group": group, "target": target, "delta_pct": delta_pct})
        else:
            verdict = "ok"

        report["results"].append(
            {
                "group": group,
                "target": target,
                "category": category,
                "verdict": verdict,
                "baseline_p50_ms": baseline_p50,
                "current_p50_ms": current_p50,
                "delta_pct": delta_pct,
                "runs": current_result.get("runs", []),
                "summaries": current_result.get("summaries")
                or summarize_runs(current_result.get("runs", [])),
            }
        )

    env_div = env_divergence(baseline, current)
    runtime_div = runtime_divergence(baseline, current)
    incompatible = bool(env_div) or bool(runtime_div)
    if incompatible:
        exit_code = 2
    elif core_regressions:
        exit_code = 1
    else:
        exit_code = 0

    report["compare"] = {
        "baseline": {
            "git_commit": baseline.get("git_commit"),
            "aiosdeck_version": baseline.get("aiosdeck_version"),
        },
        "current": {
            "git_commit": current.get("git_commit"),
            "aiosdeck_version": current.get("aiosdeck_version"),
        },
        "threshold_pct": threshold,
        "live_run": bool(live),
        "exit_code": exit_code,
        "env_divergence": env_div,
        "runtime_divergence": runtime_div,
        "core_regressions": core_regressions,
        "runtime_warnings": runtime_warnings,
        "skipped": skipped,
    }
    return report
