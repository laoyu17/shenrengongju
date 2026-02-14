"""Simulation engine interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from rtos_sim.events import SimEvent
from rtos_sim.model import ModelSpec


class ISimEngine(ABC):
    """Simulation engine contract."""

    @abstractmethod
    def build(self, spec: ModelSpec) -> None:
        """Build internal runtime state from model spec."""

    @abstractmethod
    def run(self, until: float | None = None) -> None:
        """Run simulation until horizon."""

    @abstractmethod
    def step(self, delta: float | None = None) -> None:
        """Run one simulation step."""

    @abstractmethod
    def pause(self) -> None:
        """Pause simulation loop (for UI control)."""

    @abstractmethod
    def reset(self) -> None:
        """Reset engine state."""

    @abstractmethod
    def subscribe(self, handler: Callable[[SimEvent], None]) -> None:
        """Subscribe event handler."""
