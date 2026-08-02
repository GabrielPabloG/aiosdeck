"""JavaScript/TypeScript project detector."""

import json
from pathlib import Path

from aios.context.packet import ProjectInfo, ToolsInfo


class JavaScriptDetector:
    @staticmethod
    def name() -> str:
        return "javascript"

    @staticmethod
    def detect(project_path: Path) -> tuple[ProjectInfo, ToolsInfo] | None:
        package_json = project_path / "package.json"
        tsconfig = project_path / "tsconfig.json"

        if not package_json.exists():
            return None

        language = "typescript" if tsconfig.exists() else "javascript"
        project = ProjectInfo(language=language, root=str(project_path))
        tools = ToolsInfo()

        try:
            data = json.loads(package_json.read_text())
        except (json.JSONDecodeError, OSError):
            return project, tools

        dev_deps = data.get("devDependencies", {})

        tools.dependency_manager = JavaScriptDetector._detect_dep_manager(project_path)
        tools.linter = JavaScriptDetector._detect_linter(dev_deps)
        tools.formatter = JavaScriptDetector._detect_formatter(dev_deps)
        tools.test_runner = JavaScriptDetector._detect_test_runner(dev_deps)

        return project, tools

    @staticmethod
    def _detect_dep_manager(project_path: Path) -> str:
        if (project_path / "pnpm-lock.yaml").exists():
            return "pnpm"
        if (project_path / "yarn.lock").exists():
            return "yarn"
        if (project_path / "bun.lockb").exists():
            return "bun"
        return "npm"

    @staticmethod
    def _detect_linter(dev_deps: dict) -> str:
        if "eslint" in dev_deps:
            return "eslint"
        if "biome" in dev_deps:
            return "biome"
        return "eslint"

    @staticmethod
    def _detect_formatter(dev_deps: dict) -> str:
        if "prettier" in dev_deps:
            return "prettier"
        if "biome" in dev_deps:
            return "biome"
        return "prettier"

    @staticmethod
    def _detect_test_runner(dev_deps: dict) -> str:
        if "vitest" in dev_deps:
            return "vitest"
        if "jest" in dev_deps:
            return "jest"
        return "vitest"
