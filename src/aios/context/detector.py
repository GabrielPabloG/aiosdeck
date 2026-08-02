"""Language detector protocol."""

from pathlib import Path
from typing import Protocol, runtime_checkable

from aios.context.packet import ProjectInfo, ToolsInfo


@runtime_checkable
class LanguageDetector(Protocol):
    """Protocol for language-specific project detectors."""

    @staticmethod
    def name() -> str: ...

    @staticmethod
    def detect(project_path: Path) -> tuple[ProjectInfo, ToolsInfo] | None: ...
