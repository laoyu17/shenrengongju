"""Constant execution time model."""

from __future__ import annotations

from .base import IExecutionTimeModel


class ConstantExecutionTimeModel(IExecutionTimeModel):
    """Estimate execution time by WCET/core_speed."""

    def estimate(
        self,
        segment_wcet: float,
        core_speed: float,
        now: float,  # noqa: ARG002
        *,
        task_id: str | None = None,  # noqa: ARG002
        subtask_id: str | None = None,  # noqa: ARG002
        segment_id: str | None = None,  # noqa: ARG002
        core_id: str | None = None,  # noqa: ARG002
    ) -> float:
        return segment_wcet / core_speed

    def on_exec(self, segment_key: str, core_id: str, dt: float) -> None:  # noqa: ARG002
        return
