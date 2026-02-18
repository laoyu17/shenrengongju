"""Resource protocol abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ResourceRequestResult:
    granted: bool
    reason: str = ""
    priority_updates: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ResourceReleaseResult:
    woken: list[str] = field(default_factory=list)
    priority_updates: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ResourceRuntimeSpec:
    bound_core_id: str
    ceiling_priority: float = 0.0


class IResourceProtocol(ABC):
    """Resource protocol interface for mutual exclusion and priority rules."""

    @abstractmethod
    def configure(self, resources: dict[str, ResourceRuntimeSpec]) -> None:
        """Initialize protocol with per-resource runtime attributes."""

    @abstractmethod
    def request(
        self, segment_key: str, resource_id: str, core_id: str, priority: float
    ) -> ResourceRequestResult:
        """Try to acquire a resource for a segment."""

    @abstractmethod
    def release(self, segment_key: str, resource_id: str) -> ResourceReleaseResult:
        """Release a resource and return wakeup/priority update info."""

    def cancel_segment(self, segment_key: str) -> ResourceReleaseResult:  # noqa: ARG002
        """Best-effort cleanup when a segment is aborted/cancelled."""
        return ResourceReleaseResult()

    def on_block(self, segment_key: str, resource_id: str) -> None:  # noqa: ARG002
        """Optional callback when segment blocks on a resource."""

    def on_wake(self, segment_key: str, resource_id: str) -> None:  # noqa: ARG002
        """Optional callback when segment is woken by resource release."""

    def update_resource_ceilings(self, ceilings: dict[str, float]) -> None:  # noqa: ARG002
        """Optional callback to update runtime resource ceiling values."""

    def set_priority_domain(self, domain: str) -> None:  # noqa: ARG002
        """Optional callback to annotate the priority domain used by protocol metadata."""
