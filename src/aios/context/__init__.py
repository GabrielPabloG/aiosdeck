"""Context Engine — detects project characteristics and assembles ContextPacket."""

import logging
from pathlib import Path

from aios.context.collectors import DETECTORS
from aios.context.packet import (
    ContextPacket,
    DockerInfo,
    GitInfo,
    RuntimeInfo,
    StructureInfo,
)

logger = logging.getLogger("aios.context")


class ContextEngine:
    name = "context"

    def __init__(self, project_path: Path | None = None) -> None:
        self._project_path = project_path or Path.cwd()
        self.context: ContextPacket | None = None

    def initialize(self) -> None:
        self.context = self._detect()

    def health_check(self) -> bool:
        return self.context is not None

    def shutdown(self) -> None:
        self.context = None

    def _detect(self) -> ContextPacket:
        packet = ContextPacket()
        packet.project.root = str(self._project_path)
        packet.project.name = self._project_path.name

        for detector_class in DETECTORS:
            result = detector_class.detect(self._project_path)
            if result is not None:
                project, tools = result
                packet.project = project
                packet.tools = tools
                logger.debug(
                    "Detected %s project (%s, %s, %s)",
                    project.language,
                    tools.linter,
                    tools.formatter,
                    tools.test_runner,
                )
                break

        packet.git = GitInfo.detect(self._project_path)
        packet.docker = DockerInfo.detect(self._project_path)
        packet.runtime = RuntimeInfo.detect()
        packet.structure = StructureInfo.detect(self._project_path)

        return packet
