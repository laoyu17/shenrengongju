"""Metrics interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from rtos_sim.events import SimEvent


class IMetric(ABC):
    """Metrics consumer interface."""

    @abstractmethod
    def consume(self, event: SimEvent) -> None:
        """Consume one event."""

    @abstractmethod
    def report(self) -> dict:
        """Return metric report."""

    @abstractmethod
    def reset(self) -> None:
        """Reset internal state."""
