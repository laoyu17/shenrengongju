"""Rate-monotonic scheduler."""

from __future__ import annotations

from rtos_sim.model import ReadySegment

from .base import PriorityScheduler


class RMScheduler(PriorityScheduler):
    """Fixed-priority scheduler derived from task period."""

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params=params)

    def priority_key(self, segment: ReadySegment, now: float) -> tuple:  # noqa: ARG002
        period = segment.task_period if segment.task_period is not None else float("inf")
        deadline = segment.absolute_deadline if segment.absolute_deadline is not None else float("inf")
        return (-segment.priority_value, period, deadline, *self.tie_break_key(segment))
