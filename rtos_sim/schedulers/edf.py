"""Earliest deadline first scheduler."""

from __future__ import annotations

from rtos_sim.model import ReadySegment

from .base import PriorityScheduler


class EDFScheduler(PriorityScheduler):
    """Global EDF on ready segments."""

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params=params)

    def priority_key(self, segment: ReadySegment, now: float) -> tuple:
        deadline = segment.absolute_deadline if segment.absolute_deadline is not None else float("inf")
        return (-segment.priority_value, deadline, *self.tie_break_key(segment))
