"""Deadlock-related audit checks."""

from __future__ import annotations

from typing import Any

from rtos_sim.analysis.audit_report_builder import CheckOutcome, make_check_outcome


def _event_segment_key(event: dict[str, Any]) -> str | None:
    payload = event.get("payload", {})
    if isinstance(payload, dict):
        segment_key = payload.get("segment_key")
        if isinstance(segment_key, str) and segment_key:
            return segment_key
    return None


def _find_wait_cycle(wait_for: dict[str, str], start: str) -> list[str]:
    index_by_segment: dict[str, int] = {}
    path: list[str] = []
    cursor = start
    while cursor in wait_for:
        if cursor in index_by_segment:
            return path[index_by_segment[cursor] :]
        index_by_segment[cursor] = len(path)
        path.append(cursor)
        cursor = wait_for[cursor]
    return []


def evaluate_wait_for_deadlock(events: list[dict[str, Any]]) -> CheckOutcome:
    wait_for: dict[str, str] = {}
    resource_owner: dict[str, str] = {}
    deadlock_samples: list[dict[str, Any]] = []
    observed_cycles: set[tuple[str, ...]] = set()
    for event in events:
        event_type = str(event.get("type", ""))
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}
        segment_key = _event_segment_key(event)
        resource_id = event.get("resource_id")
        job_id = event.get("job_id")

        if event_type == "ResourceAcquire":
            if (
                isinstance(resource_id, str)
                and resource_id
                and isinstance(segment_key, str)
                and segment_key
            ):
                resource_owner[resource_id] = segment_key
                wait_for.pop(segment_key, None)
            continue

        if event_type == "ResourceRelease":
            if (
                isinstance(resource_id, str)
                and resource_id
                and isinstance(segment_key, str)
                and segment_key
                and resource_owner.get(resource_id) == segment_key
            ):
                resource_owner.pop(resource_id, None)
            continue

        if event_type == "SegmentBlocked":
            if payload.get("reason") != "resource_busy":
                continue
            if not isinstance(segment_key, str) or not segment_key:
                continue
            owner_segment = payload.get("owner_segment")
            if (
                (not isinstance(owner_segment, str) or not owner_segment)
                and isinstance(resource_id, str)
                and resource_id
            ):
                owner_segment = resource_owner.get(resource_id)
            if not isinstance(owner_segment, str) or not owner_segment or owner_segment == segment_key:
                continue
            wait_for[segment_key] = owner_segment
            cycle = _find_wait_cycle(wait_for, segment_key)
            if not cycle:
                continue
            cycle_key = tuple(sorted(cycle))
            if cycle_key in observed_cycles:
                continue
            observed_cycles.add(cycle_key)
            deadlock_samples.append(
                {
                    "event_id": event.get("event_id"),
                    "cycle_segments": cycle,
                    "resource_id": resource_id,
                }
            )
            continue

        if event_type == "SegmentUnblocked" and isinstance(segment_key, str) and segment_key:
            wait_for.pop(segment_key, None)
            continue

        if event_type == "JobComplete" and isinstance(job_id, str) and job_id:
            prefix = f"{job_id}:"
            for waiter in [key for key in wait_for if key.startswith(prefix)]:
                wait_for.pop(waiter, None)
            for rid, owner in list(resource_owner.items()):
                if owner.startswith(prefix):
                    resource_owner.pop(rid, None)
            continue

        if event_type == "DeadlineMiss" and isinstance(job_id, str) and job_id:
            if not payload.get("abort_on_miss"):
                continue
            prefix = f"{job_id}:"
            for waiter in [key for key in wait_for if key.startswith(prefix)]:
                wait_for.pop(waiter, None)
            for rid, owner in list(resource_owner.items()):
                if owner.startswith(prefix):
                    resource_owner.pop(rid, None)

    issues: list[dict[str, Any]] = []
    if deadlock_samples:
        issues.append(
            {
                "rule": "wait_for_deadlock",
                "severity": "error",
                "message": "wait-for cycle detected among blocked segments",
                "samples": deadlock_samples[:20],
            }
        )

    return make_check_outcome(
        rule="wait_for_deadlock",
        passed=not deadlock_samples,
        issues=issues,
    )
