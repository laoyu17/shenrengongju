"""Resource protocol abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(slots=True)
class ResourceRequestResult:
    granted: bool
    reason: str = ""


class IResourceProtocol(ABC):
    """Resource protocol interface for mutual exclusion and priority rules."""

    @abstractmethod
    def configure(self, resources: dict[str, str]) -> None:
        """Initialize protocol with resource->bound_core mapping."""

    @abstractmethod
    def request(self, segment_key: str, resource_id: str, core_id: str) -> ResourceRequestResult:
        """Try to acquire a resource for a segment."""

    @abstractmethod
    def release(self, segment_key: str, resource_id: str) -> list[str]:
        """Release a resource and return woken segment keys."""

    def on_block(self, segment_key: str, resource_id: str) -> None:  # noqa: ARG002
        """Optional callback when segment blocks on a resource."""

    def on_wake(self, segment_key: str, resource_id: str) -> None:  # noqa: ARG002
        """Optional callback when segment is woken by resource release."""
