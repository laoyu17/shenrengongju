"""Scheduler registry and factory."""

from __future__ import annotations

from collections.abc import Callable

from .base import IScheduler
from .edf import EDFScheduler
from .rm import RMScheduler


SchedulerFactory = Callable[..., IScheduler]


_REGISTRY: dict[str, SchedulerFactory] = {
    "edf": lambda params=None: EDFScheduler(params=params),
    "earliest_deadline_first": lambda params=None: EDFScheduler(params=params),
    "rm": lambda params=None: RMScheduler(params=params),
    "rate_monotonic": lambda params=None: RMScheduler(params=params),
    "fixed_priority": lambda params=None: RMScheduler(params=params),
}


def register_scheduler(name: str, factory: SchedulerFactory) -> None:
    _REGISTRY[name.lower()] = factory


def create_scheduler(name: str, params: dict | None = None) -> IScheduler:  # noqa: ARG001
    key = name.lower()
    if key not in _REGISTRY:
        raise ValueError(f"unknown scheduler {name}")
    factory = _REGISTRY[key]
    try:
        return factory(params or {})
    except TypeError:
        return factory()
