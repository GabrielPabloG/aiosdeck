"""Shell project detector."""

from pathlib import Path

from aios.context.packet import ProjectInfo, ToolsInfo


class ShellDetector:
    @staticmethod
    def name() -> str:
        return "shell"

    @staticmethod
    def detect(project_path: Path) -> tuple[ProjectInfo, ToolsInfo] | None:
        sh_files = list(project_path.glob("*.sh")) + list(project_path.glob("src/*.sh"))
        has_makefile = (project_path / "Makefile").exists()

        if not sh_files and not has_makefile:
            return None

        project = ProjectInfo(language="shell", root=str(project_path))
        tools = ToolsInfo(
            linter="shellcheck",
            formatter="shfmt",
            test_runner="bats",
            dependency_manager="none",
        )

        return project, tools
