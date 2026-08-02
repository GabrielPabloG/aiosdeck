"""Events Engine — skeleton for v0.1."""

import logging

from aios.events.bus import EventBus

logger = logging.getLogger("aios.events")


class EventsEngine:
    name = "events"

    def __init__(self) -> None:
        self.bus: EventBus | None = None

    def initialize(self) -> None:
        self.bus = EventBus()

    def health_check(self) -> bool:
        return self.bus is not None

    def shutdown(self) -> None:
        self.bus = None
