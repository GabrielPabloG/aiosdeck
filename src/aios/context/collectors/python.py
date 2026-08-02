"""Python project detector."""

from pathlib import Path

from aios.context.packet import ProjectInfo, ToolsInfo


class PythonDetector:
    @staticmethod
    def name() -> str:
        return "python"

    @staticmethod
    def detect(project_path: Path) -> tuple[ProjectInfo, ToolsInfo] | None:
        pyproject = project_path / "pyproject.toml"
        setup_py = project_path / "setup.py"
        requirements = project_path / "requirements.txt"

        if not (pyproject.exists() or setup_py.exists() or requirements.exists()):
            return None

        project = ProjectInfo(language="python", root=str(project_path))
        tools = ToolsInfo()

        if pyproject.exists():
            content = pyproject.read_text()
            tools.dependency_manager = PythonDetector._detect_dep_manager(content)
            tools.linter = PythonDetector._detect_linter(content)
            tools.formatter = PythonDetector._detect_formatter(content)
            tools.test_runner = PythonDetector._detect_test_runner(content)

        return project, tools

    @staticmethod
    def _detect_dep_manager(content: str) -> str:
        if "[tool.uv]" in content:
            return "uv"
        if "[tool.poetry]" in content:
            return "poetry"
        if "[project]" in content or "[tool.setuptools]" in content:
            return "pip"
        return "pip"

    @staticmethod
    def _detect_linter(content: str) -> str:
        if "ruff" in content:
            return "ruff"
        if "flake8" in content or "setup.cfg" in content:
            return "flake8"
        return "ruff"

    @staticmethod
    def _detect_formatter(content: str) -> str:
        if "black" in content:
            return "black"
        if "ruff" in content:
            return "ruff"
        return "black"

    @staticmethod
    def _detect_test_runner(content: str) -> str:
        if "pytest" in content:
            return "pytest"
        return "pytest"
