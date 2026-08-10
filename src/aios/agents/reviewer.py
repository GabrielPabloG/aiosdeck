"""ReviewerAgent — read-only specialist that evaluates code and returns a structured review.

It NEVER writes code and NEVER asks the user anything. The public API is
``review()``: it scans a target path with deterministic local detectors and
returns a structured report. ``execute()`` is the internal generic adapter
used by AgentExecutor — it delegates to ``review()``.
"""

import json
import logging
import os
from pathlib import Path

from aios.agents.base import BaseAgent
from aios.agents.contracts import (
    RUNTIME_ERROR,
    STATE_FAILED,
    AgentError,
    coerce_task,
)
from aios.agents.detectors import (
    build_summary,
    compute_stats,
    scan_docstrings,
    scan_long_functions,
    scan_secrets,
    scan_todos,
    scan_unsafe,
)
from aios.agents.models import AgentResult

logger = logging.getLogger("aios.agent.reviewer")

DEFAULT_LEVEL = "conventions"
VALID_LEVELS = ("architecture", "conventions", "security")

_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    "node_modules",
    "site-packages",
}
_PY_EXTENSIONS = (".py", ".pyw")

_ARCH_SUGGESTIONS = {
    "missing-package-init": "Add an __init__.py to declare this directory a package",
    "init-missing-docstring": "Document the package purpose in __init__.py",
}


class ReviewerAgent(BaseAgent):
    """Critiques code, architecture, and conventions.  Read-only — does not
    modify files, only produces review reports."""
    name = "reviewer"
    timeout = 60.0
    required_capabilities = ["filesystem_read"]
    required_skills = ["project-dna", "coding-style"]

    def __init__(self, level: str | None = None) -> None:
        super().__init__()
        self._default_level = level if level in VALID_LEVELS else DEFAULT_LEVEL

    def _review(
        self,
        target: str | Path,
        level: str | None = None,
        options: dict | None = None,
    ) -> dict:
        """Review a target path at the given level.

        Args:
            target: A file or directory to review.
            level: One of "architecture", "conventions", "security".
            options: Reserved for future tuning.

        Returns:
            Structured report: {"items", "stats", "summary"}.
        """
        level = level if level in VALID_LEVELS else self._default_level
        target_path = Path(target).expanduser()

        if target_path.is_dir():
            files = self._discover_python_files(target_path)
        elif target_path.is_file():
            files = [target_path]
        else:
            return self._report([], error=f"target not found: {target}")

        items: list[dict] = []
        base = target_path if target_path.is_dir() else target_path.parent
        for path in sorted(files):
            items.extend(self._scan_file(path, level, base))
        if level == "architecture" and target_path.is_dir():
            items.extend(self._scan_package_structure(target_path, base))
        return self._report(items)

    def execute(self, task, context) -> AgentResult:
        """Contract method — target/level are derived from the AgentTask params.

        ``_review()`` remains the deterministic internal implementation.
        """
        agent_task = coerce_task(task)
        if agent_task.params.get("target"):
            target: str | Path = agent_task.params["target"]
        elif agent_task.files:
            target = agent_task.files[0]
        else:
            target = Path.cwd()
        level = agent_task.params.get("level")
        if level not in VALID_LEVELS:
            level = agent_task.task_type if agent_task.task_type in VALID_LEVELS else None
        report = self._review(target, level, agent_task.params.get("options"))
        if "target not found" in report["summary"]:
            return AgentResult(
                success=False,
                errors=[report["summary"]],
                error=AgentError(code=RUNTIME_ERROR, message=report["summary"]),
                error_code=RUNTIME_ERROR,
                status=STATE_FAILED,
                agent=self.name,
                task_id=agent_task.task_id,
                correlation_id=agent_task.correlation_id,
            )
        return AgentResult(
            success=True,
            output=json.dumps(report, indent=2),
            agent=self.name,
            task_id=agent_task.task_id,
            correlation_id=agent_task.correlation_id,
        )

    def _discover_python_files(self, target: Path) -> list[Path]:
        files: list[Path] = []
        for root, dirs, names in os.walk(target):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
            files.extend(Path(root) / name for name in names if name.endswith(_PY_EXTENSIONS))
        return files

    def _scan_file(self, path: Path, level: str, base: Path) -> list[dict]:
        if not path.name.endswith(_PY_EXTENSIONS):
            return []
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        rel = str(path.relative_to(base))
        items: list[dict] = []
        if level in ("conventions", "security"):
            items.extend(scan_todos(text, rel))
        if level == "conventions":
            items.extend(scan_docstrings(text, rel))
            items.extend(scan_long_functions(text, rel))
        if level == "security":
            items.extend(scan_secrets(text, rel))
            items.extend(scan_unsafe(text, rel))
        return items

    def _scan_package_structure(self, target: Path, base: Path) -> list[dict]:
        items: list[dict] = []
        for sub in sorted(p for p in target.iterdir() if p.is_dir()):
            if sub.name in _SKIP_DIRS or sub.name.startswith("."):
                continue
            if not any(p.name.endswith(_PY_EXTENSIONS) for p in sub.iterdir()):
                continue
            rel = str(sub.relative_to(base))
            init = sub / "__init__.py"
            if not init.exists():
                items.append(
                    self._arch_item(
                        "missing-package-init",
                        rel,
                        0,
                        f"Package {sub.name} is missing __init__.py",
                    )
                )
            else:
                init_text = init.read_text(encoding="utf-8", errors="replace")
                if init_text.strip() and not init_text.lstrip().startswith(('"""', "'''")):
                    items.append(
                        self._arch_item(
                            "init-missing-docstring",
                            rel,
                            1,
                            f"Package {sub.name} __init__.py missing docstring",
                        )
                    )
        return items

    @staticmethod
    def _arch_item(rule: str, file: str, line: int, message: str) -> dict:
        return {
            "id": "",
            "rule": rule,
            "severity": "warning" if rule == "missing-package-init" else "info",
            "file": file,
            "line": line,
            "message": message,
            "suggestion": _ARCH_SUGGESTIONS.get(rule, ""),
        }

    @staticmethod
    def _report(items: list[dict], error: str | None = None) -> dict:
        if error:
            return {
                "items": [],
                "stats": {"errors": 0, "warnings": 0, "infos": 0},
                "summary": error,
            }
        for index, item in enumerate(items):
            item["id"] = f"R{index + 1:03d}"
        stats = compute_stats(items)
        return {"items": items, "stats": stats, "summary": build_summary(items, stats)}
