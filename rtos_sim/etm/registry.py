"""ETM registry."""

from __future__ import annotations

from collections.abc import Callable

from .base import IExecutionTimeModel
from .constant import ConstantExecutionTimeModel


ETMFactory = Callable[[], IExecutionTimeModel]


_REGISTRY: dict[str, ETMFactory] = {
    "constant": ConstantExecutionTimeModel,
    "default": ConstantExecutionTimeModel,
}


def register_etm(name: str, factory: ETMFactory) -> None:
    _REGISTRY[name.lower()] = factory


def create_etm(name: str = "default") -> IExecutionTimeModel:
    key = name.lower()
    if key not in _REGISTRY:
        raise ValueError(f"unknown execution time model {name}")
    return _REGISTRY[key]()
