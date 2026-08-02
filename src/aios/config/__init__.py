"""Config engine — implements the Engine protocol for configuration loading."""

import logging
from pathlib import Path

from aios.config.loader import ConfigLoader
from aios.config.schema import AiosDeckConfig

logger = logging.getLogger("aios.config")


class ConfigEngine:
    name = "config"

    def __init__(self, project_path: Path | None = None) -> None:
        self._project_path = project_path or Path.cwd()
        self.config: AiosDeckConfig | None = None

    def initialize(self) -> None:
        loader = ConfigLoader(project_path=self._project_path)
        self.config = loader.load()
        logger.debug("Configuration loaded (%d sources)", len(self.config._sources))

    def health_check(self) -> bool:
        return self.config is not None

    def shutdown(self) -> None:
        self.config = None
