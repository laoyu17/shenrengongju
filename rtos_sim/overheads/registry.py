"""Overhead model registry."""

from __future__ import annotations

from collections.abc import Callable

from .base import IOverheadModel
from .simple import SimpleOverheadModel


OverheadFactory = Callable[[dict], IOverheadModel]


def _simple_factory(params: dict) -> IOverheadModel:
    return SimpleOverheadModel(
        context_switch=float(params.get("context_switch", 0.0)),
        migration=float(params.get("migration", 0.0)),
        schedule=float(params.get("schedule", 0.0)),
    )


_REGISTRY: dict[str, OverheadFactory] = {
    "simple": _simple_factory,
    "default": _simple_factory,
}


def register_overhead_model(name: str, factory: OverheadFactory) -> None:
    _REGISTRY[name.lower()] = factory


def create_overhead_model(name: str = "default", params: dict | None = None) -> IOverheadModel:
    key = name.lower()
    if key not in _REGISTRY:
        raise ValueError(f"unknown overhead model {name}")
    return _REGISTRY[key](params or {})
