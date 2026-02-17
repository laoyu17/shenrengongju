"""Resource protocol registry."""

from __future__ import annotations

from collections.abc import Callable

from .base import IResourceProtocol
from .mutex import MutexResourceProtocol
from .pcp import PCPResourceProtocol
from .pip import PIPResourceProtocol


ProtocolFactory = Callable[[], IResourceProtocol]


_REGISTRY: dict[str, ProtocolFactory] = {
    "mutex": MutexResourceProtocol,
    "pip": PIPResourceProtocol,
    "pcp": PCPResourceProtocol,
}


def register_protocol(name: str, factory: ProtocolFactory) -> None:
    _REGISTRY[name.lower()] = factory


def create_protocol(name: str) -> IResourceProtocol:
    key = name.lower()
    if key not in _REGISTRY:
        raise ValueError(f"unknown resource protocol {name}")
    return _REGISTRY[key]()
