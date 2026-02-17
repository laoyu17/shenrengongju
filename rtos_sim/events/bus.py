"""Event bus with sequence assignment."""

from __future__ import annotations

import random
import uuid
from typing import Callable

from .types import EventType, SimEvent


EventHandler = Callable[[SimEvent], None]


class EventBus:
    """Simple in-process pub/sub event bus."""

    def __init__(
        self,
        *,
        event_id_mode: str = "deterministic",
        event_id_seed: int | None = None,
    ) -> None:
        self._handlers: list[EventHandler] = []
        self._seq = 0
        self._event_id_mode = event_id_mode.lower().strip()
        self._rng = random.Random(event_id_seed)

    def subscribe(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    def _next_event_id(self) -> str:
        if self._event_id_mode == "random":
            return str(uuid.uuid4())
        if self._event_id_mode == "seeded_random":
            # Keep stable event ids for the same seed while remaining pseudo-random.
            value = self._rng.getrandbits(128)
            return f"{value:032x}"
        return f"evt-{self._seq:08d}"

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
            event_id=self._next_event_id(),
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
