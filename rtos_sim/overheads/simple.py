"""Simple constant overhead model."""

from __future__ import annotations

from .base import IOverheadModel


class SimpleOverheadModel(IOverheadModel):
    """Use constant overhead values from configuration."""

    def __init__(
        self,
        context_switch: float = 0.0,
        migration: float = 0.0,
        schedule: float = 0.0,
    ) -> None:
        self._context_switch = max(0.0, context_switch)
        self._migration = max(0.0, migration)
        self._schedule = max(0.0, schedule)

    def on_context_switch(self, job_id: str, core_id: str) -> float:  # noqa: ARG002
        return self._context_switch

    def on_migration(self, job_id: str, from_core: str, to_core: str) -> float:  # noqa: ARG002
        return self._migration

    def on_schedule(self, scheduler_name: str) -> float:  # noqa: ARG002
        return self._schedule
