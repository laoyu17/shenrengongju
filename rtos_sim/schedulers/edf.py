"""Earliest deadline first scheduler."""

from __future__ import annotations

from rtos_sim.model import ReadySegment

from .base import PriorityScheduler


class EDFScheduler(PriorityScheduler):
    """Global EDF on ready segments."""

    def priority_key(self, segment: ReadySegment, now: float) -> tuple:
        deadline = segment.absolute_deadline if segment.absolute_deadline is not None else float("inf")
        return (deadline, segment.release_time, segment.key)
