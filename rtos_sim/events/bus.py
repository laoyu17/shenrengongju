"""Event bus with sequence assignment."""

from __future__ import annotations

import uuid
from typing import Callable

from .types import EventType, SimEvent


EventHandler = Callable[[SimEvent], None]


class EventBus:
    """Simple in-process pub/sub event bus."""

    def __init__(self) -> None:
        self._handlers: list[EventHandler] = []
        self._seq = 0

    def subscribe(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    def publish(
        self,
        *,
        event_type: EventType,
        time: float,
        correlation_id: str,
        job_id: str | None = None,
        segment_id: str | None = None,
        core_id: str | None = None,
        resource_id: str | None = None,
        payload: dict | None = None,
    ) -> SimEvent:
        event = SimEvent(
            event_id=str(uuid.uuid4()),
            seq=self._seq,
            correlation_id=correlation_id,
            time=time,
            type=event_type,
            job_id=job_id,
            segment_id=segment_id,
            core_id=core_id,
            resource_id=resource_id,
            payload=payload or {},
        )
        self._seq += 1
        for handler in list(self._handlers):
            handler(event)
        return event

    def reset(self) -> None:
        self._seq = 0
        self._handlers.clear()
