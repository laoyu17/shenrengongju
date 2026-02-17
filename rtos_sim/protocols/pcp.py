"""Priority Ceiling Protocol (PCP) resource protocol."""

from __future__ import annotations

from collections import defaultdict

from .base import IResourceProtocol, ResourceReleaseResult, ResourceRequestResult, ResourceRuntimeSpec


class PCPResourceProtocol(IResourceProtocol):
    """Mutex + priority ceiling boosting for current lock holders."""

    def __init__(self) -> None:
        self._bound_cores: dict[str, str] = {}
        self._ceilings: dict[str, float] = {}
        self._owners: dict[str, str | None] = {}
        self._waiters: dict[str, list[tuple[int, str, float]]] = defaultdict(list)
        self._held_by_segment: dict[str, set[str]] = defaultdict(set)
        self._segment_base_priority: dict[str, float] = {}
        self._segment_effective_priority: dict[str, float] = {}
        self._ceiling_blocked: dict[str, tuple[str, float]] = {}
        self._waiter_order = 0

    def configure(self, resources: dict[str, ResourceRuntimeSpec]) -> None:
        self._bound_cores = {resource_id: spec.bound_core_id for resource_id, spec in resources.items()}
        self._ceilings = {resource_id: spec.ceiling_priority for resource_id, spec in resources.items()}
        self._owners = {resource_id: None for resource_id in resources}
        self._waiters = defaultdict(list)
        self._held_by_segment = defaultdict(set)
        self._segment_base_priority = {}
        self._segment_effective_priority = {}
        self._ceiling_blocked = {}
        self._waiter_order = 0

    def request(
        self, segment_key: str, resource_id: str, core_id: str, priority: float
    ) -> ResourceRequestResult:
        if self._bound_cores[resource_id] != core_id:
            return ResourceRequestResult(False, "bound_core_violation")

        self._register_segment_priority(segment_key, priority)
        self._ceiling_blocked.pop(segment_key, None)
        owner = self._owners[resource_id]
        if owner is None:
            system_ceiling = self._current_system_ceiling(excluding_segment=segment_key)
            if system_ceiling is not None and priority <= system_ceiling + 1e-12:
                self._ceiling_blocked[segment_key] = (resource_id, priority)
                self.on_block(segment_key, resource_id)
                return ResourceRequestResult(
                    False,
                    "system_ceiling_block",
                    metadata={"system_ceiling": system_ceiling},
                )
            self._owners[resource_id] = segment_key
            self._held_by_segment[segment_key].add(resource_id)
            updates = self._recompute_segment_priority(segment_key)
            return ResourceRequestResult(
                True,
                priority_updates=updates,
                metadata={"ceiling_priority": self._ceilings.get(resource_id, priority)},
            )
        if owner == segment_key:
            updates = self._recompute_segment_priority(segment_key)
            return ResourceRequestResult(True, priority_updates=updates)

        self._enqueue_waiter(resource_id, segment_key, priority)
        self.on_block(segment_key, resource_id)
        return ResourceRequestResult(False, "resource_busy", metadata={"owner_segment": owner})

    def release(self, segment_key: str, resource_id: str) -> ResourceReleaseResult:
        if self._owners[resource_id] != segment_key:
            return ResourceReleaseResult()

        self._ceiling_blocked.pop(segment_key, None)
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

        for deferred_segment in self._try_wake_ceiling_blocked():
            woken.append(deferred_segment)

        updates.update(self._recompute_segment_priority(segment_key))
        return ResourceReleaseResult(woken=woken, priority_updates=updates)

    def _try_wake_ceiling_blocked(self) -> list[str]:
        woken: list[str] = []
        for segment_key in list(self._ceiling_blocked):
            target_resource, priority = self._ceiling_blocked[segment_key]
            if self._owners.get(target_resource) is not None:
                continue
            system_ceiling = self._current_system_ceiling(excluding_segment=segment_key)
            if system_ceiling is not None and priority <= system_ceiling + 1e-12:
                continue
            self._ceiling_blocked.pop(segment_key, None)
            self.on_wake(segment_key, target_resource)
            woken.append(segment_key)
        return woken

    def _current_system_ceiling(self, excluding_segment: str | None = None) -> float | None:
        current: float | None = None
        for resource_id, owner in self._owners.items():
            if owner is None:
                continue
            if excluding_segment is not None and owner == excluding_segment:
                continue
            ceiling = self._ceilings.get(resource_id)
            if ceiling is None:
                continue
            if current is None or ceiling > current:
                current = ceiling
        return current

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
        effective = base
        for resource_id in self._held_by_segment.get(segment_key, set()):
            effective = max(effective, self._ceilings.get(resource_id, base))
        prev = self._segment_effective_priority.get(segment_key, base)
        self._segment_effective_priority[segment_key] = effective
        if abs(prev - effective) <= 1e-12:
            return {}
        return {segment_key: effective}
