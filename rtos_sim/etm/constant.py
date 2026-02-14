"""Constant execution time model."""

from __future__ import annotations

from .base import IExecutionTimeModel


class ConstantExecutionTimeModel(IExecutionTimeModel):
    """Estimate execution time by WCET/core_speed."""

    def estimate(self, segment_wcet: float, core_speed: float, now: float) -> float:  # noqa: ARG002
        return segment_wcet / core_speed

    def on_exec(self, segment_key: str, core_id: str, dt: float) -> None:  # noqa: ARG002
        return
