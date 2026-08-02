"""In-process event bus with topic-based pub/sub."""

import logging
from collections import defaultdict
from collections.abc import Callable

from aios.events.events import ALL_TOPICS, Event

logger = logging.getLogger("aios.events")


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)

    def publish(self, topic: str, payload=None, correlation_id: str = "") -> None:
        if topic not in ALL_TOPICS:
            logger.warning("Unknown topic: %s", topic)

        event = Event(topic=topic, payload=payload, correlation_id=correlation_id)
        handlers = self._resolve_handlers(topic)

        for handler in handlers:
            try:
                handler(event)
            except Exception as exc:  # noqa: BLE001
                logger.error("Subscriber error for %s: %s", topic, exc)

    def subscribe(self, topic: str, handler: Callable) -> None:
        self._subscribers[topic].append(handler)

    def unsubscribe(self, topic: str, handler: Callable) -> None:
        if handler in self._subscribers[topic]:
            self._subscribers[topic].remove(handler)

    def subscriber_count(self, topic: str | None = None) -> int:
        if topic:
            return len(self._subscribers.get(topic, []))
        return sum(len(v) for v in self._subscribers.values())

    def _resolve_handlers(self, topic: str) -> list[Callable]:
        exact = list(self._subscribers.get(topic, []))

        for pattern, handlers in self._subscribers.items():
            if pattern.endswith(".*") and topic.startswith(pattern[:-1]):
                exact.extend(handlers)

        return exact
