"""ETM registry."""

from __future__ import annotations

from collections.abc import Callable

from .base import IExecutionTimeModel
from .constant import ConstantExecutionTimeModel
from .table_based import TableBasedExecutionTimeModel


ETMFactory = Callable[[dict], IExecutionTimeModel]


_REGISTRY: dict[str, ETMFactory] = {
    "constant": lambda _params: ConstantExecutionTimeModel(),
    "default": lambda _params: ConstantExecutionTimeModel(),
    "table_based": lambda params: TableBasedExecutionTimeModel(params=params),
}


def register_etm(name: str, factory: ETMFactory) -> None:
    _REGISTRY[name.lower()] = factory


def create_etm(name: str = "default", params: dict | None = None) -> IExecutionTimeModel:
    key = name.lower()
    if key not in _REGISTRY:
        raise ValueError(f"unknown execution time model {name}")
    return _REGISTRY[key](params or {})
