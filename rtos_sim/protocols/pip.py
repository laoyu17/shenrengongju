"""Priority Inheritance Protocol (PIP) resource protocol."""

from __future__ import annotations

from collections import defaultdict

from .base import IResourceProtocol, ResourceReleaseResult, ResourceRequestResult, ResourceRuntimeSpec


class PIPResourceProtocol(IResourceProtocol):
    """Mutex + priority inheritance based on waiting segments."""

    def __init__(self) -> None:
        self._bound_cores: dict[str, str] = {}
        self._owners: dict[str, str | None] = {}
        self._waiters: dict[str, list[tuple[int, str, float]]] = defaultdict(list)
        self._held_by_segment: dict[str, set[str]] = defaultdict(set)
        self._segment_base_priority: dict[str, float] = {}
        self._segment_effective_priority: dict[str, float] = {}
        self._waiter_order = 0

    def configure(self, resources: dict[str, ResourceRuntimeSpec]) -> None:
        self._bound_cores = {resource_id: spec.bound_core_id for resource_id, spec in resources.items()}
        self._owners = {resource_id: None for resource_id in resources}
        self._waiters = defaultdict(list)
        self._held_by_segment = defaultdict(set)
        self._segment_base_priority = {}
        self._segment_effective_priority = {}
        self._waiter_order = 0

    def request(
        self, segment_key: str, resource_id: str, core_id: str, priority: float
    ) -> ResourceRequestResult:
        if self._bound_cores[resource_id] != core_id:
            return ResourceRequestResult(False, "bound_core_violation")

        self._register_segment_priority(segment_key, priority)

        owner = self._owners[resource_id]
        if owner is None:
            self._owners[resource_id] = segment_key
            self._held_by_segment[segment_key].add(resource_id)
            updates = self._recompute_segment_priority(segment_key)
            return ResourceRequestResult(True, priority_updates=updates)
        if owner == segment_key:
            updates = self._recompute_segment_priority(segment_key)
            return ResourceRequestResult(True, priority_updates=updates)

        self._enqueue_waiter(resource_id, segment_key, priority)
        self.on_block(segment_key, resource_id)
        updates = self._recompute_segment_priority(owner)
        metadata = {"owner_segment": owner}
        return ResourceRequestResult(
            False,
            "resource_busy",
            priority_updates=updates,
            metadata=metadata,
        )

    def release(self, segment_key: str, resource_id: str) -> ResourceReleaseResult:
        if self._owners[resource_id] != segment_key:
            return ResourceReleaseResult()

        self._owners[resource_id] = None
        self._held_by_segment[segment_key].discard(resource_id)

        woken: list[str] = []
        updates: dict[str, float] = {}
        next_waiter = self._pop_best_waiter(resource_id)
        if next_waiter is not None:
            self._owners[resource_id] = next_waiter
            self._held_by_segment[next_waiter].add(resource_id)
            self.on_wake(next_waiter, resource_id)
            woken.append(next_waiter)
            updates.update(self._recompute_segment_priority(next_waiter))

        updates.update(self._recompute_segment_priority(segment_key))
        return ResourceReleaseResult(woken=woken, priority_updates=updates)

    def cancel_segment(self, segment_key: str) -> ResourceReleaseResult:
        updates: dict[str, float] = {}
        woken: list[str] = []
        affected_owners: set[str] = set()

        for resource_id, queue in self._waiters.items():
            filtered = [item for item in queue if item[1] != segment_key]
            if len(filtered) != len(queue):
                self._waiters[resource_id] = filtered
                owner = self._owners.get(resource_id)
                if owner is not None and owner != segment_key:
                    affected_owners.add(owner)

        owned_resources = [
            resource_id
            for resource_id, owner in self._owners.items()
            if owner == segment_key
        ]
        for resource_id in owned_resources:
            release_result = self.release(segment_key, resource_id)
            woken.extend(release_result.woken)
            updates.update(release_result.priority_updates)

        for owner_segment in affected_owners:
            updates.update(self._recompute_segment_priority(owner_segment))

        self._held_by_segment.pop(segment_key, None)
        self._segment_base_priority.pop(segment_key, None)
        self._segment_effective_priority.pop(segment_key, None)
        unique_woken = list(dict.fromkeys(woken))
        return ResourceReleaseResult(woken=unique_woken, priority_updates=updates)

    def _register_segment_priority(self, segment_key: str, priority: float) -> None:
        if segment_key not in self._segment_base_priority:
            self._segment_base_priority[segment_key] = priority
            self._segment_effective_priority[segment_key] = priority

    def _enqueue_waiter(self, resource_id: str, segment_key: str, priority: float) -> None:
        queue = self._waiters[resource_id]
        for idx, (order, waiter_key, waiter_priority) in enumerate(queue):
            if waiter_key == segment_key:
                queue[idx] = (order, waiter_key, max(waiter_priority, priority))
                return
        queue.append((self._waiter_order, segment_key, priority))
        self._waiter_order += 1

    def _pop_best_waiter(self, resource_id: str) -> str | None:
        queue = self._waiters[resource_id]
        if not queue:
            return None
        best_idx = 0
        best_key = (-queue[0][2], queue[0][0])
        for idx, (order, _waiter_key, waiter_priority) in enumerate(queue[1:], start=1):
            current_key = (-waiter_priority, order)
            if current_key < best_key:
                best_idx = idx
                best_key = current_key
        _, waiter_key, _ = queue.pop(best_idx)
        return waiter_key

    def _recompute_segment_priority(self, segment_key: str) -> dict[str, float]:
        base = self._segment_base_priority.get(segment_key)
        if base is None:
            return {}
        inherited = base
        for resource_id in self._held_by_segment.get(segment_key, set()):
            for _order, _waiter, waiter_priority in self._waiters[resource_id]:
                inherited = max(inherited, waiter_priority)
        prev = self._segment_effective_priority.get(segment_key, base)
        self._segment_effective_priority[segment_key] = inherited
        if abs(prev - inherited) <= 1e-12:
            return {}
        return {segment_key: inherited}
