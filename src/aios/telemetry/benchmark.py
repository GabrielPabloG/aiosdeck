"""Benchmark measurement core — wall and CPU timing for the aios runtime.

Pure measurement logic (no CLI dispatch, no aios.cli imports) so the CLI layer
depends on this module, never the reverse. Every measurement captures
``wall_time_ms`` (via ``time.monotonic()``), ``cpu_user_ms`` and
``cpu_system_ms`` (deltas of ``os.times()``), and ``peak_memory_kb`` (process
peak RSS via ``resource.getrusage``). Metrics are owned by
:mod:`aios.telemetry.schema` — this module consumes them, it does not fork them.

Measurement contract for ``measure_lifecycle``:

``t0 -> kernel_factory(project_path) -> t1``   startup       = bootstrap + kernel construction only
``t1 -> kernel.start() -> t2``                 kernel_init   = engine init + wiring + enrich
``t2 -> kernel.get_context() -> t3``           context_load  = assembled context retrieval
``t3 -> SkillRegistry + discover -> t4``       skill_load    = registry + discovery
``t4 -> kernel.run(... mode="plan") -> t5``    plan          = planner via executor (real runtime)
``t5 -> kernel.run_agent("developer") -> t6``  agent_exec    = developer via executor (real runtime)
``t6 -> kernel.shutdown() -> t7``              telemetry_flush = engine shutdown / store flush

``startup`` never includes ``kernel.start()``; ``kernel_init`` never includes
kernel construction. The first ``kernel_factory`` call pays module-import cost;
``--warmup`` absorbs it so repeat runs measure steady state.

With ``bare_task=True`` the ``plan`` and ``agent_exec`` phases skip agents and
the executor entirely: they run a restricted runtime probe (fixed prompt, no
skills, no capabilities, empty permissions) so the elapsed time is the pure
model latency, not product latency.
"""

from __future__ import annotations

import json
import math
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

from aios import __version__
from aios.core.task import Task
from aios.telemetry.schema import METRICS

PHASES = (
    "startup",
    "kernel_init",
    "context_load",
    "skill_load",
    "plan",
    "agent_exec",
    "telemetry_flush",
)
SKIP_REASON = "requires agent runtime (--skip-agents)"
BARE_PROMPT = "You are in benchmark bare mode. Do not call tools. Reply with exactly OK."


def percentile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolated percentile of a pre-sorted list (0.0 for empty)."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (q / 100.0)
    floor = math.floor(k)
    ceil = math.ceil(k)
    if floor == ceil:
        return float(sorted_vals[int(k)])
    return sorted_vals[floor] * (ceil - k) + sorted_vals[ceil] * (k - floor)


def summarize(samples: list[float]) -> dict:
    """Summary statistics for a metric, preserving raw samples in order."""
    if not samples:
        return {
            "count": 0,
            "min": None,
            "max": None,
            "mean": None,
            "p50": None,
            "p95": None,
            "p99": None,
            "samples": [],
        }
    ordered = sorted(samples)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "max": ordered[-1],
        "mean": statistics.mean(ordered),
        "p50": percentile(ordered, 50),
        "p95": percentile(ordered, 95),
        "p99": percentile(ordered, 99),
        "samples": samples,
    }


def summarize_runs(runs: list[dict]) -> dict[str, dict]:
    """Per-metric summaries across a list of run dicts (None metrics skipped)."""
    return {
        metric: summarize([run[metric] for run in runs if run.get(metric) is not None])
        for metric in METRICS
    }


def sample_start() -> tuple[float, float, float]:
    """Snapshot (wall, user, system) at the start of a measured region."""
    times = os.times()
    return time.monotonic(), times.user, times.system


def peak_memory_kb() -> float:
    """Peak RSS of this process normalized to KB.

    Contract: ``resource.getrusage(RUSAGE_SELF).ru_maxrss`` is normalized to
    KB by platform — Linux returns KB directly, macOS returns bytes. A zero
    result (unsupported platform) still satisfies the schema, which only
    requires the metric to be present.
    """
    try:
        import resource  # noqa: PLC0415

        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except (ImportError, AttributeError, OSError):
        return 0.0
    if sys.platform == "darwin":
        return rss / 1024.0
    return float(rss)


def elapsed(wall: float, user: float, system: float, *, error: str | None = None) -> dict:
    """Delta since sample_start(), in milliseconds, with optional error."""
    times = os.times()
    entry = {
        "wall_time_ms": (time.monotonic() - wall) * 1000.0,
        "cpu_user_ms": (times.user - user) * 1000.0,
        "cpu_system_ms": (times.system - system) * 1000.0,
        "peak_memory_kb": peak_memory_kb(),
    }
    if error is not None:
        entry["error"] = error
    return entry


def error_entry(message: str) -> dict:
    """A run placeholder for a phase that could not execute at all."""
    return {
        "wall_time_ms": 0.0,
        "cpu_user_ms": 0.0,
        "cpu_system_ms": 0.0,
        "peak_memory_kb": 0.0,
        "error": message,
    }


def skipped_entry(reason: str) -> dict:
    """Marker that distinguishes 'not executed' from 'executed in 0 ms'."""
    return {"skipped": True, "reason": reason}


def measure_lifecycle(  # noqa: PLR0912, PLR0913, PLR0915
    project_path,
    kernel_factory,
    skip_agents: bool = False,
    *,
    on_phase=None,
    profile: bool = False,
    bare_task: bool = False,
    bare_model: str = "",
) -> dict:
    """Run one full 7-phase lifecycle and return per-phase timings.

    Errors never abort the measurement: a failed phase records its elapsed
    time plus the error message, and a failing kernel factory yields the
    remaining phases as ``kernel unavailable``.

    When *on_phase* is provided it is called with ``(("phase_name", "start"))``
    before and ``(("phase_name", "end", elapsed_ms))`` after the slow ``plan``,
    ``agent_exec``, and ``telemetry_flush`` phases.

    With *profile=True* the kernel is constructed with ``AIOS_PROFILE`` enabled
    so the ``kernel_init`` run carries the ``kernel.timings`` breakdown
    (optional schema field since v1.1).

    With *bare_task=True* the ``plan``/``agent_exec`` phases replace the agent
    runs with a restricted runtime probe (see :data:`BARE_PROMPT`), measuring
    pure model latency. *bare_model* pins the probe to a fixed model id so a
    full-vs-bare comparison is never a model swap. A probe whose reply is not
    "OK"-shaped records a ``warning`` on the run (tolerant, never a failure).
    """
    notify = on_phase or (lambda _e: None)
    result: dict[str, dict] = {}

    previous_profile = os.environ.get("AIOS_PROFILE")
    if profile:
        os.environ["AIOS_PROFILE"] = "1"
    try:
        wall, user, system = sample_start()
        try:
            kernel = kernel_factory(project_path)
            result["startup"] = elapsed(wall, user, system)
        except Exception as exc:  # noqa: BLE001 - minimal mode: measure without a kernel
            result["startup"] = elapsed(wall, user, system, error=str(exc))
            for phase in PHASES[1:]:
                result[phase] = error_entry("kernel unavailable")
            return result

        wall, user, system = sample_start()
        try:
            kernel.start(quiet=True)
            result["kernel_init"] = elapsed(wall, user, system)
        except Exception as exc:  # noqa: BLE001
            result["kernel_init"] = elapsed(wall, user, system, error=str(exc))
    finally:
        if profile:
            if previous_profile is None:
                os.environ.pop("AIOS_PROFILE", None)
            else:
                os.environ["AIOS_PROFILE"] = previous_profile

    if profile:
        timings = getattr(kernel, "timings", None)
        if isinstance(timings, dict) and timings:
            result["kernel_init"]["timings"] = timings

    wall, user, system = sample_start()
    try:
        kernel.get_context()
        result["context_load"] = elapsed(wall, user, system)
    except Exception as exc:  # noqa: BLE001
        result["context_load"] = elapsed(wall, user, system, error=str(exc))

    wall, user, system = sample_start()
    try:
        _measure_skill_load(project_path)
        result["skill_load"] = elapsed(wall, user, system)
    except Exception as exc:  # noqa: BLE001
        result["skill_load"] = elapsed(wall, user, system, error=str(exc))

    for phase, runner in (("plan", _run_plan), ("agent_exec", _run_agent_exec)):
        if skip_agents and not bare_task:
            result[phase] = skipped_entry(SKIP_REASON)
            continue
        notify((phase, "start"))
        wall, user, system = sample_start()
        try:
            if bare_task:
                warning = _run_bare_probe(kernel, model=bare_model)
                entry = elapsed(wall, user, system)
                if warning is not None:
                    entry["warning"] = warning
            else:
                runner(kernel)
                entry = elapsed(wall, user, system)
            result[phase] = entry
            notify((phase, "end", entry["wall_time_ms"]))
        except Exception as exc:  # noqa: BLE001 - failed agent run still measures the path
            entry = elapsed(wall, user, system, error=str(exc))
            result[phase] = entry
            notify((phase, "end", entry["wall_time_ms"]))

    notify(("telemetry_flush", "start"))
    wall, user, system = sample_start()
    try:
        kernel.shutdown()
        entry = elapsed(wall, user, system)
        result["telemetry_flush"] = entry
        notify(("telemetry_flush", "end", entry["wall_time_ms"]))
    except Exception as exc:  # noqa: BLE001
        entry = elapsed(wall, user, system, error=str(exc))
        result["telemetry_flush"] = entry
        notify(("telemetry_flush", "end", entry["wall_time_ms"]))

    return result


def measure_startup_inprocess(project_path, kernel_factory) -> dict:
    """One bootstrap sample: kernel_factory() only (no kernel.start())."""
    wall, user, system = sample_start()
    try:
        kernel_factory(project_path)
        return elapsed(wall, user, system)
    except Exception as exc:  # noqa: BLE001
        return elapsed(wall, user, system, error=str(exc))


def measure_startup_process(warmup: int, repeat: int) -> list[dict]:
    """Process-level startup: run ``python -m aios --version`` per sample."""
    command = [sys.executable, "-m", "aios", "--version"]

    def run_once() -> dict:
        wall, user, system = sample_start()
        subprocess.run(command, capture_output=True, text=True, check=False)
        return elapsed(wall, user, system)

    for _ in range(warmup):
        run_once()
    return [run_once() for _ in range(repeat)]


def baseline_path(project_path, *, bare: bool = False) -> Path:
    """Canonical baseline location: ``.aios/benchmarks/v<version>.json``.

    In bare mode the file is ``v<version>-bare.json`` so a full baseline never
    collides with the pure-model-latency baseline of the same version.
    """
    suffix = "-bare" if bare else ""
    return Path(project_path) / ".aios" / "benchmarks" / f"v{__version__}{suffix}.json"


def save_report(path: str | Path, report: dict) -> Path:
    """Persist a JSON report to ``path``, creating parent directories."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json_dumps(report), encoding="utf-8")
    return target


def load_report(path: str | Path) -> dict:
    """Load a previously saved benchmark report."""
    return json_loads(Path(path).read_text(encoding="utf-8"))


def json_dumps(report: dict) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False)


def json_loads(text: str) -> dict:
    return json.loads(text)


def _measure_skill_load(project_path) -> None:
    """Build the skill registry and run discovery (imports paid inside the phase)."""
    from aios.skills.discovery import SkillDiscoveryService  # noqa: PLC0415
    from aios.skills.registry import SkillRegistry  # noqa: PLC0415

    registry = SkillRegistry(project_path)
    discovery = SkillDiscoveryService(registry)
    discovery.discover("benchmark task")


def _run_plan(kernel) -> None:
    context = kernel.get_context() if hasattr(kernel, "get_context") else None
    task = Task(description="benchmark task", task_type="plan")
    kernel.run(task, context, mode="plan")


def _run_bare_probe(kernel, model: str = "") -> str | None:
    """One restricted runtime probe for pure model latency.

    Skips agents and the executor entirely: the runtime is invoked directly
    with no skills, no capabilities, and empty permissions, so every tool is
    structurally denied by the runtime itself. ``model`` pins the probe to a
    fixed model id (the default model) so the measurement is never a routing
    decision. The reply is scanned only as a best-effort check — a non-"OK"
    output returns a warning string, never a failure.
    """
    from aios.security.contracts import EffectivePermissions  # noqa: PLC0415

    runtime = kernel.get_engine("runtime")
    if runtime is None:
        raise RuntimeError("runtime engine not available")
    output = runtime.execute(
        BARE_PROMPT,
        [],
        [],
        permissions=EffectivePermissions(allowed=frozenset()),
        agent="benchmark",
        task_type="code",
        complexity="low",
        model=model,
    )
    if not output.strip().upper().startswith("OK"):
        return "bare probe reply is not 'OK' (tolerant check)"
    return None


def _run_agent_exec(kernel) -> None:
    context = kernel.get_context() if hasattr(kernel, "get_context") else None
    task = Task(description="benchmark task", task_type="code")
    kernel.run_agent("developer", task, context)
