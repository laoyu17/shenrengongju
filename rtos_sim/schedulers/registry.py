"""Scheduler registry and factory."""

from __future__ import annotations

from collections.abc import Callable

from .base import IScheduler
from .edf import EDFScheduler
from .rm import RMScheduler


SchedulerFactory = Callable[[], IScheduler]


_REGISTRY: dict[str, SchedulerFactory] = {
    "edf": EDFScheduler,
    "earliest_deadline_first": EDFScheduler,
    "rm": RMScheduler,
    "rate_monotonic": RMScheduler,
    "fixed_priority": RMScheduler,
}


def register_scheduler(name: str, factory: SchedulerFactory) -> None:
    _REGISTRY[name.lower()] = factory


def create_scheduler(name: str, params: dict | None = None) -> IScheduler:  # noqa: ARG001
    key = name.lower()
    if key not in _REGISTRY:
        raise ValueError(f"unknown scheduler {name}")
    return _REGISTRY[key]()
