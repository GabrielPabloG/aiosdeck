"""Benchmark CLI command — measure wall/CPU times for startup and commands.

``aios benchmark`` (no target) prints usage; ``aios benchmark phases``
profiles the 7 lifecycle phases. ``aios benchmark <command>`` times one
command; ``aios benchmark all`` times the full CLI surface (dashboard,
doctor, skills, memory, plan, backlog run). ``aios benchmark startup
--process`` measures real process startup via subprocess. ``aios benchmark
validate <file>`` checks a report against the versioned schema (exit 0/1).

Every measurement lands in the report as a flat ``results[]`` entry — the
single canonical representation. No ``phases``/``commands``/``startup``
structure survives at the top level. Command dispatch is in-process through
``kernel_factory`` (no PATH dependency, reproducible, works with a stubbed
kernel in tests).
"""

from __future__ import annotations

import contextlib
import io
import sys
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from aios import __version__
from aios.backlog.cli import cmd_backlog_run
from aios.cli.commands.core import cmd_dashboard, cmd_doctor
from aios.cli.commands.exec_cmds import cmd_plan
from aios.cli.commands.memory import cmd_memory_list
from aios.config.loader import ConfigLoader
from aios.core.console import ProgressBar, log_step
from aios.skills.cli import cmd_skills_discover
from aios.telemetry.benchmark import (
    PHASES,
    SKIP_REASON,
    elapsed,
    json_dumps,
    load_report,
    measure_lifecycle,
    measure_startup_inprocess,
    measure_startup_process,
    sample_start,
    save_report,
    skipped_entry,
    summarize_runs,
)
from aios.telemetry.compare import (
    DEFAULT_THRESHOLD_PCT,
    compare_reports,
)
from aios.telemetry.schema import (
    GROUPS,
    SCHEMA_VERSION,
    git_commit,
    system_info,
    validate_report,
)

_ALL_TARGETS = ("dashboard", "doctor", "skills", "memory", "plan", "backlog")
_AVAILABLE = ("all", "startup", "phases", "validate", "compare", *_ALL_TARGETS)

# name -> (command function, fixed args, requires agent runtime, timeout_sec)
_COMMAND_ARGS: dict[str, tuple[Callable, list[str], bool, float | None]] = {
    "dashboard": (cmd_dashboard, [], False, 5.0),
    "doctor": (cmd_doctor, [], False, None),
    "skills": (cmd_skills_discover, ["benchmark task", "--json"], False, None),
    "memory": (cmd_memory_list, [], False, None),
    "plan": (cmd_plan, ["benchmark task", "--json"], True, None),
    "backlog": (cmd_backlog_run, ["--source=board:benchmark"], True, None),
}


def cmd_benchmark(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    if raw_args and raw_args[0] == "validate":
        _cmd_validate(raw_args[1:])
        return
    if raw_args and raw_args[0] == "compare":
        _cmd_compare(raw_args[1:], project_path, kernel_factory)
        return

    opts = _parse_args(raw_args)

    report = _new_report(opts, project_path)

    command = opts["command"]
    if command is None or opts["help"]:
        _print_usage()
        return
    if command == "phases":
        report["results"].extend(_measure_phases(project_path, kernel_factory, opts))
    elif command == "all":
        report["results"].extend(_measure_all(project_path, kernel_factory, opts))
    elif command == "startup":
        report["results"].append(_measure_startup(project_path, kernel_factory, opts))
    elif command in _COMMAND_ARGS:
        report["results"].append(_measure_named(command, project_path, kernel_factory, opts))
    else:
        _error(f"Unknown benchmark target: {command}. Available: {', '.join(_AVAILABLE)}")

    if opts["bare_task"] and command != "phases":
        print("Warning: --bare-task only affects the 'phases' target", file=sys.stderr)

    if opts["output"]:
        path = save_report(opts["output"], report)
        report["output"] = str(path)

    if opts["json"]:
        print(json_dumps(report))
    else:
        _render_text(report)


def _new_report(opts: dict, project_path: Path) -> dict:
    config = ConfigLoader(project_path).load()
    return {
        "schema_version": SCHEMA_VERSION,
        "aiosdeck_version": __version__,
        "git_commit": git_commit(),
        "timestamp": datetime.now(UTC).isoformat(),
        "system_info": system_info(),
        "runtime_info": {
            "provider": config.model.default,
            "model": config.model.ollama_model,
            "host": config.model.ollama_host,
        },
        "warmup": opts["warmup"],
        "repeat": opts["repeat"],
        "skip_agents": opts["skip_agents"],
        "benchmark_mode": "bare" if opts["bare_task"] else "full",
        "task_prompt_type": "restricted_ok" if opts["bare_task"] else "full_task",
        "results": [],
    }


def _print_usage() -> None:
    print("Usage: aios benchmark <target> [options]")
    print()
    print("Targets:")
    for name in _AVAILABLE:
        print(f"  {name}")
    print()
    print("Options:")
    print("  -h, --help       Show this help and exit")
    print("  --warmup N       Warmup runs before measuring (default: 1)")
    print("  --repeat N       Measured runs per target (default: 5)")
    print("  --json           Print report as JSON")
    print("  --output PATH    Save the report to PATH")
    print("  --skip-agents    Skip targets that require an agent runtime")
    print("  --process        startup: measure a real subprocess (not in-process)")
    print("  --profile        phases: record kernel.timings breakdown (schema v1.1)")
    print("  --bare-task      phases: restricted runtime probe (pure model latency)")
    print()
    print("Validate:")
    print("  aios benchmark validate <file>   Check a report against the schema (exit 0/1)")
    print()
    print("Compare:")
    print("  aios benchmark compare <base> [<cur>]   Compare a baseline report")
    print("    one file      measure current (live full) then compare")
    print("    two files     deterministic file-to-file comparison")
    print("    --skip-agents live mode: Core phases only (skips plan/agent_exec)")


def _parse_args(raw_args: list[str]) -> dict:  # noqa: PLR0912
    opts = {
        "command": None,
        "help": False,
        "warmup": 1,
        "repeat": 5,
        "json": False,
        "output": None,
        "skip_agents": False,
        "process": False,
        "profile": False,
        "bare_task": False,
    }
    i = 0
    while i < len(raw_args):
        arg = raw_args[i]
        if arg in ("--help", "-h"):
            opts["help"] = True
        elif arg == "--json":
            opts["json"] = True
        elif arg == "--skip-agents":
            opts["skip_agents"] = True
        elif arg == "--process":
            opts["process"] = True
        elif arg == "--profile":
            opts["profile"] = True
        elif arg == "--bare-task":
            opts["bare_task"] = True
        elif arg in ("--warmup", "--repeat"):
            i += 1
            if i < len(raw_args):
                opts[arg[2:]] = int(raw_args[i])
        elif arg == "--output":
            i += 1
            if i < len(raw_args):
                opts["output"] = raw_args[i]
        elif arg.startswith("-"):
            _error(f"unknown option: {arg}")
        elif opts["command"] is None:
            opts["command"] = arg
        else:
            _error(f"unexpected argument: {arg}")
        i += 1
    return opts


def _cmd_validate(args: list[str]) -> None:
    if not args or args[0] in ("--help", "-h"):
        print("Usage: aios benchmark validate <file>", file=sys.stderr)
        sys.exit(1)
    try:
        report = load_report(args[0])
    except Exception as exc:  # noqa: BLE001 - any read/parse failure is a bad report
        print(f"Invalid benchmark report: {args[0]}\n  cannot read file: {exc}")
        sys.exit(1)
    errors = validate_report(report)
    if errors:
        print(f"Invalid benchmark report ({len(errors)} error(s)): {args[0]}")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)
    print(f"Valid benchmark report: {args[0]}")
    sys.exit(0)


def _cmd_compare(args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    opts = _parse_compare_args(args)
    if opts["help"]:
        _print_compare_usage()
        sys.exit(0)
    if not opts["files"]:
        _error("compare requires a baseline file: aios benchmark compare <baseline> [<current>]")

    try:
        baseline = load_report(opts["files"][0])
    except Exception as exc:  # noqa: BLE001 - any read/parse failure is a bad report
        _error(f"cannot read baseline report: {exc}")

    baseline_errors = validate_report(baseline)
    if baseline_errors:
        _error(f"invalid baseline report: {baseline_errors[0]}")

    live_run = len(opts["files"]) == 1
    if live_run:
        measure_opts = {
            "warmup": 1,
            "repeat": 5,
            "skip_agents": opts["skip_agents"],
            "bare_task": False,
            "profile": False,
        }
        current = _new_report(measure_opts, project_path)
        current["results"].extend(_measure_phases(project_path, kernel_factory, measure_opts))
        current["output"] = "(live run)"
    else:
        try:
            current = load_report(opts["files"][1])
        except Exception as exc:  # noqa: BLE001
            _error(f"cannot read current report: {exc}")
        current_errors = validate_report(current)
        if current_errors:
            _error(f"invalid current report: {current_errors[0]}")

    compare = compare_reports(baseline, current, threshold=opts["threshold"], live=live_run)
    if live_run:
        compare["compare"]["baseline"]["file"] = opts["files"][0]

    if opts["json"]:
        print(json_dumps(compare))
    else:
        _render_compare(compare, live_run=live_run)
    sys.exit(compare["compare"]["exit_code"])


def _parse_compare_args(args: list[str]) -> dict:
    opts = {
        "help": False,
        "json": False,
        "threshold": DEFAULT_THRESHOLD_PCT,
        "skip_agents": False,
        "files": [],
    }
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--help", "-h"):
            opts["help"] = True
        elif arg == "--json":
            opts["json"] = True
        elif arg == "--skip-agents":
            opts["skip_agents"] = True
        elif arg == "--threshold":
            i += 1
            if i < len(args):
                opts["threshold"] = float(args[i])
        elif arg.startswith("-"):
            _error(f"unknown option: {arg}")
        else:
            opts["files"].append(arg)
        i += 1
    return opts


def _print_compare_usage() -> None:
    print("Usage: aios benchmark compare <baseline.json> [<current.json>] [options]")
    print()
    print("Compare a baseline report against a current report.")
    print("  compare baseline.json               measure current (live full run) then compare")
    print("  compare baseline.json cur.json      deterministic file-to-file comparison")
    print()
    print("Options:")
    print("  -h, --help       Show this help and exit")
    print("  --json           Print the comparison report as JSON")
    print("  --threshold PCT  Regression gate on p50 (default: 10)")
    print("  --skip-agents    live mode: benchmark Core phases only (skips plan/agent_exec)")
    print()
    print("Exit codes: 0 = ok, 1 = Core regression, 2 = environment/runtime divergence")
    print("(2 > 1 > 0; a regression in an incompatible environment is never real)")


def _render_compare(report: dict, *, live_run: bool) -> None:
    summary = report["compare"]
    mode = "live (measured)" if live_run else "file-to-file"
    print(f"Compare mode: {mode} — threshold {summary['threshold_pct']:g}%")
    print(
        f"  baseline v{summary['baseline']['aiosdeck_version']} "
        f"({summary['baseline']['git_commit']}) vs current "
        f"v{summary['current']['aiosdeck_version']} ({summary['current']['git_commit']})"
    )
    if summary["env_divergence"]:
        print(f"  environment divergence: {', '.join(summary['env_divergence'])}")
    if summary["runtime_divergence"]:
        print(f"  runtime divergence: {', '.join(summary['runtime_divergence'])}")
    for group in GROUPS:
        entries = [r for r in report["results"] if r.get("group") == group]
        if not entries:
            continue
        print(f"\n{group}:")
        for entry in entries:
            _render_compare_entry(entry)
    if summary["core_regressions"]:
        print(f"\nCore regressions ({len(summary['core_regressions'])}):")
        for item in summary["core_regressions"]:
            print(f"  {item['group']}/{item['target']} +{item['delta_pct']:+.1f}%")
    if summary["runtime_warnings"]:
        print(f"\nRuntime-dependent warnings ({len(summary['runtime_warnings'])}):")
        for item in summary["runtime_warnings"]:
            print(f"  {item['group']}/{item['target']} +{item['delta_pct']:+.1f}% (corroborative)")
    print(f"\nExit code: {summary['exit_code']}")


def _render_compare_entry(entry: dict) -> None:
    label = f"  {entry['target']:<16} [{entry['category']}]"
    if entry.get("skipped"):
        print(f"{label} skipped ({entry.get('reason')})")
        return
    verdict = entry["verdict"]
    print(
        f"{label} {verdict:<10} "
        f"p50 {entry['baseline_p50_ms']:.2f} -> {entry['current_p50_ms']:.2f} "
        f"({entry['delta_pct']:+.1f}%)"
    )


def _measure_phases(project_path, kernel_factory, opts: dict) -> list[dict]:
    bar = ProgressBar(sample_total=opts["repeat"], label="phases")

    def _run_one():
        result = measure_lifecycle(
            project_path,
            kernel_factory,
            opts["skip_agents"],
            on_phase=_on_phase_for_bar(bar),
            profile=opts["profile"],
            bare_task=opts["bare_task"],
        )
        bar._advance_sample()
        return result

    profiles = _collect_samples(_run_one, opts, label="phases")
    bar._finish()

    results: list[dict] = []
    for phase in PHASES:
        runs = []
        for profile in profiles:
            entry = profile[phase]
            if entry.get("skipped"):
                results.append(
                    {
                        "group": "phases",
                        "target": phase,
                        **skipped_entry(entry.get("reason") or SKIP_REASON),
                    }
                )
                break
            runs.append(entry)
        else:
            entry = {"group": "phases", "target": phase, **_build_entry(runs)}
            if phase in ("plan", "agent_exec"):
                entry["model"] = profiles[0].get("_models", {}).get(phase, "")
            if opts["bare_task"] and phase in ("plan", "agent_exec"):
                entry["tool_calls_count"] = 0
                entry["is_read_only"] = True
            results.append(entry)
    return results


def _on_phase_for_bar(bar):
    def _handler(event: tuple) -> None:
        if event[0] in ("plan", "agent_exec", "telemetry_flush"):
            if event[1] == "start":
                bar._report_phase_start(event[0])
            elif event[1] == "end":
                bar._report_phase_end(event[0], event[2])

    return _handler


def _measure_all(project_path, kernel_factory, opts: dict) -> list[dict]:
    return [_measure_named(name, project_path, kernel_factory, opts) for name in _ALL_TARGETS]


def _measure_named(name: str, project_path, kernel_factory, opts: dict) -> dict:
    _fn, _args, needs_agent, _timeout = _COMMAND_ARGS[name]
    if needs_agent and opts["skip_agents"]:
        return {"group": "commands", "target": name, **skipped_entry(SKIP_REASON)}
    runs = _collect_samples(
        lambda: _run_command(name, project_path, kernel_factory),
        opts,
        label=name,
    )
    return {"group": "commands", "target": name, **_build_entry(runs)}


def _measure_startup(project_path, kernel_factory, opts: dict) -> dict:
    if opts["process"]:
        runs = measure_startup_process(opts["warmup"], opts["repeat"])
        return {"group": "startup", "target": "startup", "mode": "process", **_build_entry(runs)}
    runs = _collect_samples(
        lambda: measure_startup_inprocess(project_path, kernel_factory),
        opts,
        label="startup",
    )
    return {"group": "startup", "target": "startup", "mode": "in-process", **_build_entry(runs)}


def _collect_samples(run_once: Callable, opts: dict, label: str = "") -> list[dict]:
    prefix = f"{label} " if label else ""
    for i in range(opts["warmup"]):
        log_step("◐", f"{prefix}warmup {i + 1}/{opts['warmup']}")
        run_once()
    results: list[dict] = []
    for i in range(opts["repeat"]):
        log_step("▶", f"{prefix}{i + 1}/{opts['repeat']}")
        results.append(run_once())
    return results


def _run_command(name: str, project_path, kernel_factory) -> dict:
    fn, args, _needs_agent, timeout = _COMMAND_ARGS[name]
    if timeout is None:
        wall, user, system = sample_start()
        error = _run_silent(fn, list(args), project_path, kernel_factory)
        return elapsed(wall, user, system, error=error)

    wall, user, system = sample_start()
    error = _run_with_timeout(fn, list(args), project_path, kernel_factory, timeout)
    return elapsed(wall, user, system, error=error)


def _run_silent(fn, args, project_path, kernel_factory) -> str | None:
    """Execute a command with stdout/stderr suppressed (benchmark output stays clean)."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            fn(args, project_path, kernel_factory)
            return None
        except SystemExit:
            return None
        except Exception as exc:  # noqa: BLE001 - failed commands still get timed
            return str(exc)


def _run_with_timeout(fn, args, project_path, kernel_factory, timeout: float) -> str | None:
    """Cross-platform watchdog (threading, no signal.alarm) for TUI commands.

    A command that does not return within ``timeout`` records an explicit
    ``timeout`` error; the daemon thread is abandoned and dies on exit.
    """
    outcome: dict[str, str | None] = {"error": None}

    def target() -> None:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                fn(args, project_path, kernel_factory)
            except SystemExit:
                pass
            except Exception as exc:  # noqa: BLE001
                outcome["error"] = str(exc)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        outcome["error"] = f"timeout after {timeout:g}s — command did not return"
    return outcome["error"]


def _build_entry(runs: list[dict]) -> dict:
    entry = {"runs": runs, "summaries": summarize_runs(runs)}
    errors = sum(1 for run in runs if run.get("error"))
    if errors:
        entry["errors"] = errors
    warnings = [run.pop("warning") for run in runs if run.get("warning")]
    if warnings:
        entry["warnings"] = warnings
    return entry


def _render_text(report: dict) -> None:
    mode = report.get("benchmark_mode", "full")
    print(
        f"AiosDeck v{report['aiosdeck_version']} — benchmark "
        f"(warmup={report['warmup']}, repeat={report['repeat']}, "
        f"skip_agents={report['skip_agents']}, mode={mode})"
    )
    for group in GROUPS:
        entries = [result for result in report["results"] if result.get("group") == group]
        if not entries:
            continue
        if group == "phases":
            print("\nPhases (p50 ms):")
        elif group == "commands":
            print("\nCommands (p50 ms):")
        else:
            mode = next((r["mode"] for r in entries if "mode" in r), "")
            print(f"\nStartup ({mode}, p50 ms):")
        for result in entries:
            _render_entry(f"  {result['target']:<16}", result)
    if "output" in report:
        print(f"\nBaseline saved: {report['output']}")


def _render_entry(label: str, entry: dict) -> None:
    if entry.get("skipped"):
        print(f"{label} skipped")
        return
    summary = entry["summaries"].get("wall_time_ms") or {}
    p50 = summary.get("p50")
    if p50 is None:
        print(f"{label} n/a")
        return
    p95 = summary.get("p95")
    p99 = summary.get("p99")
    print(f"{label} p50 {p50:8.2f}  p95 {p95:8.2f}  p99 {p99:8.2f}")
    if entry.get("errors"):
        print(f"{label}   ({entry['errors']} error run(s))")


def _error(msg: str) -> None:
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)
