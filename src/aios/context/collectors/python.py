"""Python project detector."""

from pathlib import Path

from aios.context.packet import ProjectInfo, ToolsInfo

_SKIP_DIRS = {"venv", ".venv", "__pycache__", "node_modules", ".git", ".tox", "env"}
_MAX_DEPTH = 3


class PythonDetector:
    @staticmethod
    def name() -> str:
        return "python"

    @staticmethod
    def detect(project_path: Path) -> tuple[ProjectInfo, ToolsInfo] | None:
        root_files = PythonDetector._config_at_root(project_path)
        if root_files:
            return PythonDetector._build(project_path, root_files)

        search = PythonDetector._search_subdirs(project_path)
        if not search["has_python"]:
            return None

        return PythonDetector._build(project_path, search["config_file"])

    @staticmethod
    def _config_at_root(project_path: Path) -> Path | None:
        for name in ("pyproject.toml", "setup.py", "requirements.txt"):
            f = project_path / name
            if f.exists():
                return f
        return None

    @staticmethod
    def _search_subdirs(project_path: Path) -> dict:
        result: dict = {"has_python": False, "config_file": None}
        for item in project_path.iterdir():
            if not item.is_dir():
                continue
            if item.name in _SKIP_DIRS or item.name.startswith("."):
                continue
            found = PythonDetector._walk(item, depth=0)
            if found["has_python"]:
                result["has_python"] = True
            if found["config_file"] and not result["config_file"]:
                result["config_file"] = found["config_file"]
        return result

    @staticmethod
    def _walk(directory: Path, depth: int) -> dict:
        result: dict = {"has_python": False, "config_file": None}
        if depth >= _MAX_DEPTH:
            return result
        for item in directory.iterdir():
            if item.is_dir():
                if item.name in _SKIP_DIRS or item.name.startswith("."):
                    continue
                sub = PythonDetector._walk(item, depth + 1)
                if sub["has_python"]:
                    result["has_python"] = True
                if sub["config_file"] and not result["config_file"]:
                    result["config_file"] = sub["config_file"]
            elif item.is_file():
                if item.suffix == ".py":
                    result["has_python"] = True
                elif item.name in ("pyproject.toml", "requirements.txt", "setup.py"):
                    result["config_file"] = item
        return result

    @staticmethod
    def _build(project_path: Path, config_file: Path | None) -> tuple[ProjectInfo, ToolsInfo]:
        project = ProjectInfo(language="python", root=str(project_path))
        tools = ToolsInfo()
        if config_file and config_file.exists():
            content = config_file.read_text()
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
        if "flake8" in content:
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
