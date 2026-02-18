"""Mutex resource protocol implementation."""

from __future__ import annotations

from collections import defaultdict, deque

from .base import IResourceProtocol, ResourceReleaseResult, ResourceRequestResult, ResourceRuntimeSpec


class MutexResourceProtocol(IResourceProtocol):
    """FIFO mutex with bound-core check."""

    def __init__(self) -> None:
        self._bound_cores: dict[str, str] = {}
        self._owners: dict[str, str | None] = {}
        self._waiters: dict[str, deque[str]] = defaultdict(deque)

    def configure(self, resources: dict[str, ResourceRuntimeSpec]) -> None:
        self._bound_cores = {resource_id: spec.bound_core_id for resource_id, spec in resources.items()}
        self._owners = {resource_id: None for resource_id in resources}
        self._waiters = defaultdict(deque)

    def request(
        self, segment_key: str, resource_id: str, core_id: str, priority: float  # noqa: ARG002
    ) -> ResourceRequestResult:
        bound_core = self._bound_cores[resource_id]
        if bound_core != core_id:
            return ResourceRequestResult(False, "bound_core_violation")

        owner = self._owners[resource_id]
        if owner is None:
            self._owners[resource_id] = segment_key
            return ResourceRequestResult(True)
        if owner == segment_key:
            return ResourceRequestResult(True)

        if segment_key not in self._waiters[resource_id]:
            self._waiters[resource_id].append(segment_key)
        self.on_block(segment_key, resource_id)
        return ResourceRequestResult(
            False,
            "resource_busy",
            metadata={"owner_segment": owner},
        )

    def release(self, segment_key: str, resource_id: str) -> ResourceReleaseResult:
        if self._owners[resource_id] != segment_key:
            return ResourceReleaseResult()
        self._owners[resource_id] = None
        woken: list[str] = []
        if self._waiters[resource_id]:
            next_segment = self._waiters[resource_id].popleft()
            self._owners[resource_id] = next_segment
            self.on_wake(next_segment, resource_id)
            woken.append(next_segment)
        return ResourceReleaseResult(woken=woken)

    def cancel_segment(self, segment_key: str) -> ResourceReleaseResult:
        owns_any = any(owner == segment_key for owner in self._owners.values())
        waits_any = any(segment_key in waiters for waiters in self._waiters.values())
        if not owns_any and not waits_any:
            return ResourceReleaseResult()

        woken: list[str] = []

        for resource_id, waiters in self._waiters.items():
            filtered = deque(waiter for waiter in waiters if waiter != segment_key)
            self._waiters[resource_id] = filtered

        owned_resources = [
            resource_id
            for resource_id, owner in self._owners.items()
            if owner == segment_key
        ]
        for resource_id in owned_resources:
            release_result = self.release(segment_key, resource_id)
            woken.extend(release_result.woken)

        return ResourceReleaseResult(woken=list(dict.fromkeys(woken)))
