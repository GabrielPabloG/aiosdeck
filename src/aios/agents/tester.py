"""Minimal TesterAgent scaffold.

Responsibilities:
- Run test suites (pytest) under a target path.
- Return a structured report dict.
"""

import re
import subprocess
import sys
from pathlib import Path

from aios.agents.base import BaseAgent


class TesterAgent(BaseAgent):
    __test__ = False  # pytest: class name matches the Test* collection pattern

    name = "tester"
    required_capabilities = ["filesystem_read", "shell"]
    required_skills = ["project-dna", "coding-style"]

    def __init__(self, python: str | None = None) -> None:
        self._python = python or sys.executable

    def run(self, target: str | Path, dry_run: bool = True) -> dict:
        """Run pytest under a target path and return a structured report.

        Args:
            target: A directory or file to run tests against.
            dry_run: When True, only collect tests — nothing is executed.

        Returns:
            Structured report: {"target", "dry_run", "status", "returncode",
            "collected", "passed", "failed", "errors"}.
        """
        target_path = Path(target).expanduser()
        if not target_path.exists():
            return self._error_report(str(target_path), dry_run, f"target not found: {target}")

        collected = self._collect_count(target_path)
        if dry_run:
            return {
                "target": str(target_path),
                "dry_run": True,
                "status": "ok",
                "returncode": 0,
                "collected": collected,
                "passed": 0,
                "failed": 0,
                "errors": [],
            }

        try:
            result = subprocess.run(
                [self._python, "-m", "pytest", "-p", "no:cacheprovider", "-q", str(target_path)],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return self._error_report(str(target_path), dry_run, str(exc))

        output = result.stdout + result.stderr
        return {
            "target": str(target_path),
            "dry_run": False,
            "status": "ok" if result.returncode == 0 else "failed",
            "returncode": result.returncode,
            "collected": collected,
            "passed": _parse_count(output, "passed"),
            "failed": _parse_count(output, "failed"),
            "errors": (
                [line for line in output.splitlines() if line.strip()]
                if result.returncode != 0
                else []
            ),
        }

    def _collect_count(self, target_path: Path) -> int:
        try:
            result = subprocess.run(
                [
                    self._python,
                    "-m",
                    "pytest",
                    "-p",
                    "no:cacheprovider",
                    "--collect-only",
                    str(target_path),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return 0
        return _parse_collected(result.stdout + result.stderr)

    @staticmethod
    def _error_report(target: str, dry_run: bool, message: str) -> dict:
        return {
            "target": target,
            "dry_run": dry_run,
            "status": "error",
            "returncode": None,
            "collected": 0,
            "passed": 0,
            "failed": 0,
            "errors": [message],
        }


def _parse_collected(output: str) -> int:
    match = re.search(r"collected\s+(\d+)\s+item", output)
    return int(match.group(1)) if match else 0


def _parse_count(output: str, label: str) -> int:
    match = re.search(rf"(\d+)\s+{label}", output)
    return int(match.group(1)) if match else 0
