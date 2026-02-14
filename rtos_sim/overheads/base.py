"""Overhead model abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod


class IOverheadModel(ABC):
    """Provide additional delay for scheduling operations."""

    @abstractmethod
    def on_context_switch(self, job_id: str, core_id: str) -> float:
        """Context switch overhead in simulation time unit."""

    @abstractmethod
    def on_migration(self, job_id: str, from_core: str, to_core: str) -> float:
        """Migration overhead in simulation time unit."""

    @abstractmethod
    def on_schedule(self, scheduler_name: str) -> float:
        """Scheduler decision overhead."""
