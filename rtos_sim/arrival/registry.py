"""Arrival-generator registry."""

from __future__ import annotations

from collections.abc import Callable

from .base import IArrivalGenerator
from .builtins import (
    ConstantIntervalArrivalGenerator,
    PoissonRateArrivalGenerator,
    SequenceArrivalGenerator,
    UniformIntervalArrivalGenerator,
)


ArrivalGeneratorFactory = Callable[[], IArrivalGenerator]


_REGISTRY: dict[str, ArrivalGeneratorFactory] = {
    "constant_interval": ConstantIntervalArrivalGenerator,
    "uniform_interval": UniformIntervalArrivalGenerator,
    "poisson_rate": PoissonRateArrivalGenerator,
    "sequence": SequenceArrivalGenerator,
}


def register_arrival_generator(name: str, factory: ArrivalGeneratorFactory) -> None:
    _REGISTRY[name.strip().lower()] = factory


def create_arrival_generator(name: str) -> IArrivalGenerator:
    key = name.strip().lower()
    if key not in _REGISTRY:
        raise ValueError(f"unknown arrival generator {name}")
    return _REGISTRY[key]()
