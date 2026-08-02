"""Engine protocol — every subsystem must implement this."""

import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger("aios.engine")


@runtime_checkable
class Engine(Protocol):
    """Protocol that every AiosDeck engine must implement."""

    name: str

    def initialize(self) -> None:
        """Called at session start. Set up connections, load config."""

    def health_check(self) -> bool:
        """Return True if the engine is operational."""
        ...

    def shutdown(self) -> None:
        """Called at session end. Clean up resources."""
