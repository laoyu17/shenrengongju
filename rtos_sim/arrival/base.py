"""Arrival-process generator abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from random import Random
from typing import Any

from rtos_sim.model import TaskGraphSpec


class IArrivalGenerator(ABC):
    """Plugin contract for custom arrival-process intervals."""

    @abstractmethod
    def next_interval(
        self,
        *,
        task: TaskGraphSpec,
        now: float,
        current_release: float,
        release_index: int,
        params: dict[str, Any],
        rng: Random,
    ) -> float:
        """Return the next release interval (>0)."""
