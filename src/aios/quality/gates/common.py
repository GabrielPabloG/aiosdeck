"""Shared helpers for concrete quality gates."""

from __future__ import annotations

import asyncio
from pathlib import Path

from aios.quality.contracts import GateFinding, GateInput, severity_mapper

_PY_SUFFIXES = (".py", ".pyi")


def python_files(gate_input: GateInput) -> list[str]:
    """Relative python file paths — explicit list or project scan.

    An explicit ``files`` list wins; otherwise top-level and ``src/`` files
    are discovered. Deterministic ordering for reproducible findings.
    """
    if gate_input.files:
        return sorted(f for f in gate_input.files if f.endswith(_PY_SUFFIXES))
    base = gate_input.project_path or Path.cwd()
    rels = [
        p.relative_to(base).as_posix()
        for p in base.glob("*")
        if p.is_file() and p.name.endswith(_PY_SUFFIXES)
    ]
    src = base / "src"
    if src.is_dir():
        rels.extend(p.relative_to(base).as_posix() for p in src.glob("**/*.py") if p.is_file())
    return sorted(rels)


async def read_text(path: Path) -> str:
    """Read a small project file off the event loop thread."""
    return await asyncio.to_thread(_read_sync, path)


def _read_sync(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


async def run_cmd(cmd: list[str], *, timeout: float = 60.0) -> tuple[int, str]:
    """Run a subprocess and capture combined stdout+stderr."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        return 1, "command timed out"
    returncode = proc.returncode if proc.returncode is not None else 1
    return returncode, stdout.decode("utf-8", errors="replace")


def reviewer_finding(item: dict, category: str) -> GateFinding:
    """Convert a detectors.py finding dict into a canonical GateFinding."""
    return GateFinding(
        id=item["rule"],
        title=item["message"],
        detail=f"{item['file']}:{item['line']}",
        severity=severity_mapper(item["severity"]),
        category=category,
        evidence=item["message"],
    )
