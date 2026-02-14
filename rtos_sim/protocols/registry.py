"""Resource protocol registry."""

from __future__ import annotations

from collections.abc import Callable

from .base import IResourceProtocol
from .mutex import MutexResourceProtocol


ProtocolFactory = Callable[[], IResourceProtocol]


_REGISTRY: dict[str, ProtocolFactory] = {
    "mutex": MutexResourceProtocol,
    # Current MVP keeps pip/pcp aliases mapped to mutex behavior.
    "pip": MutexResourceProtocol,
    "pcp": MutexResourceProtocol,
}


def register_protocol(name: str, factory: ProtocolFactory) -> None:
    _REGISTRY[name.lower()] = factory


def create_protocol(name: str) -> IResourceProtocol:
    key = name.lower()
    if key not in _REGISTRY:
        raise ValueError(f"unknown resource protocol {name}")
    return _REGISTRY[key]()
