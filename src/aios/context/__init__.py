"""Context Engine — detects project characteristics and assembles ContextPacket."""

import logging
from pathlib import Path

from aios.context.assembler import ContextAssembler
from aios.context.assembly import (
    DEFAULT_LAYER_CAPS,
    ContextAssemblyResult,
    assemble_layers,
    dedupe_layers,
    order_layers,
    truncate_layers,
)
from aios.context.collectors import DETECTORS
from aios.context.layers import (
    GUARDRAIL_LAYERS,
    LAYER_PRECEDENCE,
    Layer,
    LayeredContext,
    LayerType,
    empty_layers,
)
from aios.context.packet import (
    ContextPacket,
    DockerInfo,
    GitInfo,
    RuntimeInfo,
    StructureInfo,
)
from aios.core.profiler import NullProfiler, Profiler

__all__ = [
    "DEFAULT_LAYER_CAPS",
    "ContextAssemblyResult",
    "ContextAssembler",
    "GUARDRAIL_LAYERS",
    "LAYER_PRECEDENCE",
    "Layer",
    "LayerType",
    "LayeredContext",
    "assemble_layers",
    "dedupe_layers",
    "empty_layers",
    "order_layers",
    "truncate_layers",
]

logger = logging.getLogger("aios.context")


class ContextEngine:
    name = "context"

    def __init__(self, project_path: Path | None = None) -> None:
        self._project_path = project_path or Path.cwd()
        self.context: ContextPacket | None = None
        self._profiler: Profiler = NullProfiler()

    def set_profiler(self, profiler: Profiler) -> None:
        self._profiler = profiler

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

        packet.git = self._time_detector("git", GitInfo.detect, self._project_path)
        packet.docker = self._time_detector("docker", DockerInfo.detect, self._project_path)
        packet.runtime = self._time_detector("runtime", RuntimeInfo.detect)
        packet.structure = self._time_detector(
            "structure", StructureInfo.detect, self._project_path
        )

        return packet

    def _time_detector(self, name: str, detect, *args):
        """Run a detector under the profiler; timing survives a failure."""
        with self._profiler.measure_detector(name):
            return detect(*args)
