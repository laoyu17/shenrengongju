"""Execution time model abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod


class IExecutionTimeModel(ABC):
    """Execution-time estimation plugin."""

    @abstractmethod
    def estimate(self, segment_wcet: float, core_speed: float, now: float) -> float:
        """Estimate actual execution time of a segment on a core."""

    @abstractmethod
    def on_exec(self, segment_key: str, core_id: str, dt: float) -> None:
        """Observe execution progress for adaptive models."""
