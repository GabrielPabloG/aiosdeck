"""Execution CLI commands — plan, research, review.

Each function is a command entry-point extracted from commands.py.
These commands trigger agent execution through the Kernel.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from aios.agents.contracts import AgentTask
from aios.core.console import ProgressSpinner, log_step
from aios.core.run_result import RunResult, StageSummary
from aios.core.task import Task
from aios.research.schema import research_result_from_dict, research_result_to_json
from aios.security.cli import _render_intent_summary

_REVIEW_LEVELS = ("architecture", "conventions", "security")
_REVIEW_OUTPUTS = ("text", "json", "file")
_RESEARCH_SCOPES = ("repo", "docs", "web", "mixed")


def _error(msg: str) -> None:
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════
# Review
# ═══════════════════════════════════════════════════════════════


def _parse_review_args(raw_args: list[str]) -> dict:
    opts: dict = {
        "level": "conventions",
        "output": "text",
        "dry_run": False,
        "diff_only": False,
        "target": None,
    }
    i = 0
    while i < len(raw_args):
        arg = raw_args[i]
        if arg == "--dry-run":
            opts["dry_run"] = True
        elif arg == "--diff":
            opts["diff_only"] = True
        elif arg in ("--level", "--output"):
            i += 1
            value = raw_args[i] if i < len(raw_args) else ""
            choices = _REVIEW_LEVELS if arg == "--level" else _REVIEW_OUTPUTS
            if value not in choices:
                _error(f"{arg} must be one of {', '.join(choices)}")
            opts["level" if arg == "--level" else "output"] = value
        elif arg.startswith("-"):
            _error(f"unknown option {arg}")
        elif opts["target"] is None:
            opts["target"] = arg
        i += 1
    return opts


def _print_review_text(report: dict) -> None:
    print(report["summary"])
    for item in report.get("items", [])[:20]:
        line = item.get("line", "?")
        print(f"{item['severity'].upper()}: {item['file']}:{line} {item['message']}")


def cmd_review(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    opts = _parse_review_args(raw_args or [])
    target = opts["target"] or str(Path.cwd())

    kernel = kernel_factory(project_path)
    kernel.start()

    if opts["diff_only"]:
        target = _resolve_diff_target(target)

    task = AgentTask(
        description=f"review {target}",
        task_type="review",
        params={"target": target, "level": opts["level"]},
    )

    with ProgressSpinner("Reviewing"):
        result = kernel.run_agent("reviewer", task)

    if not result.success:
        _error(result.errors[0] if result.errors else "Review failed")
    report = json.loads(result.output)

    if opts["dry_run"]:
        report["summary"] = f"{report['summary']} (dry-run, read-only)"
        print(json.dumps(report, indent=2))
        return
    if opts["output"] == "json":
        print(json.dumps(report, indent=2))
        return
    if opts["output"] == "file":
        with Path("reviewer_report.json").open("w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print("Wrote report: reviewer_report.json")
        return
    _print_review_text(report)


def _resolve_diff_target(target: str) -> str:
    result = subprocess.run(
        ["git", "diff", "HEAD", "--name-only"],
        capture_output=True,
        text=True,
        check=False,
        cwd=target,
    )
    names = [line for line in result.stdout.splitlines() if line]
    if not names:
        return target
    diff_dir = Path(tempfile.mkdtemp(prefix="aios-review-diff-"))
    for name in names:
        source = Path(target) / name
        if source.is_file():
            dest = diff_dir / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(source.read_text(encoding="utf-8", errors="replace"))
    return str(diff_dir)


# ═══════════════════════════════════════════════════════════════
# Research
# ═══════════════════════════════════════════════════════════════


def cmd_research(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    opts: dict = {"scope": "mixed", "json": False, "output": None}
    positional: list[str] = []
    i = 0
    while i < len(raw_args or []):
        arg = raw_args[i]
        if arg == "--json":
            opts["json"] = True
        elif arg == "--scope":
            i += 1
            value = raw_args[i] if i < len(raw_args) else ""
            if value not in _RESEARCH_SCOPES:
                _error(f"--scope must be one of {', '.join(_RESEARCH_SCOPES)}")
            opts["scope"] = value
        elif arg == "--output":
            i += 1
            value = raw_args[i] if i < len(raw_args) else ""
            if not value:
                _error("--output requires a file path")
            opts["output"] = value
        elif arg.startswith("-"):
            _error(f"unknown option {arg}")
        else:
            positional.append(arg)
        i += 1

    question = " ".join(positional).strip()
    if not question:
        print(
            "Usage: aios research <question> "
            "[--scope repo|docs|web|mixed] [--json] [--output FILE]",
            file=sys.stderr,
        )
        sys.exit(1)

    kernel = kernel_factory(project_path)
    kernel.start()

    context = kernel.get_context()
    task = AgentTask(
        description=question,
        task_type="research",
        params={"scope": opts["scope"]},
    )

    with ProgressSpinner("Researching"):
        result = kernel.run_agent("research", task, context)

    if not result.success:
        _error(result.errors[0] if result.errors else "Research failed")
    research = research_result_from_dict(json.loads(result.output))

    if opts["output"]:
        with Path(opts["output"]).open("w", encoding="utf-8") as f:
            f.write(research_result_to_json(research) + "\n")
        print(f"Wrote research report: {opts['output']}")
        return
    if opts["json"]:
        print(research_result_to_json(research))
        return

    _print_research_text(research)


def _print_research_text(result) -> None:
    print(f"status: {result.status}")
    print(f"summary: {result.summary_short}")
    print(f"confidence: {result.confidence_overall:.2f}")
    if result.error:
        print(f"error: {result.error}")

    if result.findings:
        print("\nFindings:")
        for f in result.findings:
            confidence = f"{f.confidence:.2f}"
            print(f"  - [{f.id}] (conf {confidence}) {f.claim}")
    elif result.sources:
        print("\nNo findings synthesized.")

    if result.sources:
        print("\nSources:")
        for s in result.sources:
            print(f"  - {s.type}: {s.title} ({s.url})")

    if result.recommendations:
        print("\nRecommendations:")
        for r in result.recommendations:
            print(f"  - [{r.priority}] {r.action}")

    if result.memory_candidates:
        print("\nMemory candidates (advisory, not persisted):")
        for m in result.memory_candidates:
            print(f"  - [{m.kind}] {m.content}")


# ═══════════════════════════════════════════════════════════════
# Plan
# ═══════════════════════════════════════════════════════════════


def cmd_plan(raw_args: list[str], project_path: Path, kernel_factory: Callable) -> None:
    run_mode = "--run" in (raw_args or [])
    as_json = "--json" in (raw_args or [])
    debug_context = "--debug-context" in (raw_args or [])

    clean_args = [a for a in (raw_args or []) if a not in ("--run", "--json", "--debug-context")]
    intent = " ".join(clean_args) if clean_args else None
    if not intent:
        print("Usage: aios plan <intent>", file=sys.stderr)
        print("Example: aios plan 'add OAuth2 login'", file=sys.stderr)
        sys.exit(1)

    kernel = kernel_factory(project_path)
    kernel.start()

    context = kernel.get_context()
    task = Task(description=intent, task_type="plan")
    mode = "plan-run" if run_mode else "plan"

    if debug_context:
        _render_debug_context(kernel, task, context, agent="planner", as_json=as_json)

    with ProgressSpinner("Running workflow" if run_mode else "Planning"):
        result = kernel.run(
            task,
            context,
            mode=mode,
            on_stage=_render_stage if run_mode else None,
        )

    if as_json:
        print(json.dumps(_run_result_to_json(result), indent=2))
        if not result.success:
            sys.exit(1)
        return

    _render_run_result(result)
    if run_mode:
        _render_gate_trail(result)
        _render_intent_summary(result)

    if not result.success:
        for err in result.errors:
            print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)


def _render_debug_context(kernel, task, context, *, agent: str, as_json: bool) -> None:
    from aios.context.assembler import ContextAssembler  # noqa: PLC0415
    from aios.context.cli import render_layer_tree  # noqa: PLC0415

    try:
        knowledge = kernel.get_engine("knowledge")
        assembler = ContextAssembler(knowledge=knowledge)
        assembly = assembler.assemble(task, context, agent=agent)
    except Exception:
        return
    print(f"[Context Layers · {agent}]")
    print(render_layer_tree(assembly, as_json=as_json))


def _run_result_to_json(result: RunResult) -> dict:
    return {
        "success": result.success,
        "errors": list(result.errors),
        "gates": _gates_json(result),
    }


def _gates_json(result: RunResult) -> dict:
    gates = {}
    for stage in result.stages:
        if not stage.name.endswith("_gate"):
            continue
        details = stage.details or {}
        gate = details.get("gate") or {}
        gates[stage.name] = {
            "status": gate.get("status", stage.status),
            "reason": stage.reason or gate.get("reason", ""),
            "findings": gate.get("findings", []),
            "policy": details.get("policy", {}),
        }
    return gates


def _render_gate_trail(result: RunResult) -> None:
    gate_stages = [s for s in result.stages if s.name.endswith("_gate")]
    if not gate_stages:
        return
    log_step("", "Quality Gates:")
    for stage in gate_stages:
        label, detail = _gate_label(stage)
        line = f"  [{label}] {stage.name}"
        if detail:
            line += f"  {detail}"
        log_step("", line)


def _gate_label(stage: StageSummary) -> tuple[str, str]:
    details = stage.details or {}
    gate = details.get("gate") or {}
    policy = details.get("policy") or {}
    status = gate.get("status", stage.status)
    if status == "skipped":
        return "SKIP", "(skipped)"
    if policy.get("overridden"):
        return "PASS", f"(override: {policy.get('override_reason', '')})"
    if policy.get("decision") == "warn":
        return "PASS", "(warn)"
    if stage.status == "failed" or status in ("failed", "error"):
        reason = stage.reason or gate.get("reason", "")
        return "FAIL", f"- {reason}"
    return "PASS", ""


def _render_plan_list(plan: dict) -> None:
    subtasks = plan.get("subtasks", [])
    if not subtasks:
        print("No subtasks to execute.")
        return
    log_step("📋", f"Plano de Execução ({len(subtasks)} tarefas):")
    for st in subtasks:
        log_step("", f"  • {st['description']}")


def _render_stage(stage: StageSummary) -> None:
    if stage.name == "planner":
        plan = (stage.details or {}).get("plan")
        if stage.status == "success" and plan:
            _render_plan_list(plan)
        return
    if stage.name.startswith("developer:"):
        description = (stage.details or {}).get("description", stage.name)
        mark = "✓" if stage.status == "success" else "✗"
        print(f"  [{mark}] {description}")


def _render_run_result(result: RunResult) -> None:
    if result.subtask_count:
        print(f"\n{result.completed_count}/{result.subtask_count} tasks completed")
    elif result.output:
        print(result.output)
