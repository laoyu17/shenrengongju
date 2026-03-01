"""Dispatch-phase helpers for ``SimEngine``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rtos_sim.events import EventType
from rtos_sim.model import RuntimeSegmentState

if TYPE_CHECKING:
    from .engine import SimEngine


def apply_dispatch(
    engine: SimEngine,
    job_id: str,
    decision_segment_id: str | None,
    core_id: str,
    now: float,
) -> str:
    assert engine._etm and engine._overheads

    if job_id in engine._aborted_jobs:
        return "noop"
    core = engine._cores[core_id]
    if core.running_segment_key is not None:
        return "noop"

    candidates = [
        key
        for key in engine._ready
        if key.startswith(f"{job_id}:")
        and (
            decision_segment_id is None
            or decision_segment_id in (key, engine._segments[key].segment_id)
        )
    ]
    if not candidates:
        return "noop"

    segment_key = sorted(candidates)[0]
    segment = engine._segments[segment_key]
    if segment.finished or segment.job_id in engine._aborted_jobs:
        engine._ready.discard(segment_key)
        return "dropped"
    if segment.mapping_hint is not None and segment.mapping_hint != core_id:
        engine._event_bus.publish(
            event_type=EventType.ERROR,
            time=now,
            correlation_id=segment.job_id,
            job_id=segment.job_id,
            segment_id=segment.segment_id,
            core_id=core_id,
            payload={
                "reason": "mapping_hint_violation",
                "segment_key": segment_key,
                "expected_core": segment.mapping_hint,
                "requested_core": core_id,
            },
        )
        engine._abort_job(segment.job_id, now, preempt_reason="abort_on_error")
        return "error"

    acquired_resources_this_dispatch: list[str] = []
    for resource_id in segment.required_resources:
        if resource_id in engine._held_resources[segment_key]:
            continue
        protocol = engine._protocol_for_resource(resource_id)
        request_priority = segment.effective_priority
        result = protocol.request(segment_key, resource_id, core_id, request_priority)
        if result.priority_updates:
            engine._apply_priority_updates(result.priority_updates)
        if not result.granted:
            rollback_released: list[str] = []
            if (
                engine._resource_acquire_policy == "atomic_rollback"
                and acquired_resources_this_dispatch
                and result.reason != "bound_core_violation"
            ):
                rollback_released = rollback_dispatch_resources(
                    engine,
                    segment=segment,
                    segment_key=segment_key,
                    resource_ids=acquired_resources_this_dispatch,
                    now=now,
                    core_id=core_id,
                )
            segment.blocked = True
            segment.waiting_resource = resource_id
            engine._ready.discard(segment_key)
            engine._event_bus.publish(
                event_type=EventType.SEGMENT_BLOCKED,
                time=now,
                correlation_id=segment.job_id,
                job_id=segment.job_id,
                segment_id=segment.segment_id,
                core_id=core_id,
                resource_id=resource_id,
                payload={
                    "reason": result.reason,
                    "segment_key": segment_key,
                    "request_priority": request_priority,
                    "resource_acquire_policy": engine._resource_acquire_policy,
                    "rollback_applied": bool(rollback_released),
                    "rollback_released_resources": sorted(rollback_released),
                    **result.metadata,
                },
            )
            if result.reason == "bound_core_violation":
                engine._event_bus.publish(
                    event_type=EventType.ERROR,
                    time=now,
                    correlation_id=segment.job_id,
                    job_id=segment.job_id,
                    segment_id=segment.segment_id,
                    core_id=core_id,
                    resource_id=resource_id,
                    payload={
                        "reason": "bound_core_violation",
                        "segment_key": segment_key,
                        "requested_core": core_id,
                        "resource_id": resource_id,
                        **result.metadata,
                    },
                )
                engine._abort_job(segment.job_id, now, preempt_reason="abort_on_error")
                return "error"
            return "blocked"
        engine._held_resources[segment_key].add(resource_id)
        acquired_resources_this_dispatch.append(resource_id)
        engine._event_bus.publish(
            event_type=EventType.RESOURCE_ACQUIRE,
            time=now,
            correlation_id=segment.job_id,
            job_id=segment.job_id,
            segment_id=segment.segment_id,
            core_id=core_id,
            resource_id=resource_id,
            payload={
                "segment_key": segment_key,
                "request_priority": request_priority,
                **result.metadata,
            },
        )

    migration_cost = 0.0
    previous_core = segment.running_on
    if previous_core and previous_core != core_id:
        migration_cost = engine._overheads.on_migration(segment.job_id, previous_core, core_id)
        engine._event_bus.publish(
            event_type=EventType.MIGRATE,
            time=now,
            correlation_id=segment.job_id,
            job_id=segment.job_id,
            segment_id=segment.segment_id,
            core_id=core_id,
            payload={
                "from_core": previous_core,
                "to_core": core_id,
                "reason": "segment_redispatch",
                "segment_key": segment_key,
            },
        )

    context_cost = engine._overheads.on_context_switch(segment.job_id, core_id)
    execution_time = engine._etm.estimate(
        segment.remaining_time,
        core.speed,
        now,
        task_id=segment.task_id,
        subtask_id=segment.subtask_id,
        segment_id=segment.segment_id,
        core_id=core_id,
    )
    total_runtime = migration_cost + context_cost + execution_time

    segment.running_on = core_id
    if segment.started_at is None:
        segment.started_at = now
    segment.blocked = False

    engine._ready.discard(segment_key)
    core.running_segment_key = segment_key
    core.running_since = now
    core.finish_time = now + total_runtime

    engine._event_bus.publish(
        event_type=EventType.SEGMENT_START,
        time=now,
        correlation_id=segment.job_id,
        job_id=segment.job_id,
        segment_id=segment.segment_id,
        core_id=core_id,
        payload={
            "segment_key": segment_key,
            "estimated_finish": core.finish_time,
            "execution_time": execution_time,
            "context_overhead": context_cost,
            "migration_overhead": migration_cost,
            "deterministic_window_id": segment.deterministic_window_id,
            "deterministic_offset_index": segment.deterministic_offset_index,
        },
    )
    return "started"


def rollback_dispatch_resources(
    engine: SimEngine,
    *,
    segment: RuntimeSegmentState,
    segment_key: str,
    resource_ids: list[str],
    now: float,
    core_id: str,
) -> list[str]:
    released: list[str] = []
    for resource_id in reversed(resource_ids):
        if resource_id not in engine._held_resources.get(segment_key, set()):
            continue
        protocol = engine._protocol_for_resource(resource_id)
        release_result = protocol.release(segment_key, resource_id)
        if release_result.priority_updates:
            engine._apply_priority_updates(release_result.priority_updates)
        on_resource_release_result(
            engine,
            segment=segment,
            segment_key=segment_key,
            resource_id=resource_id,
            release_result=release_result,
            now=now,
            core_id=core_id,
            reason_override="acquire_rollback",
        )
        engine._held_resources[segment_key].discard(resource_id)
        released.append(resource_id)
    return released


def on_resource_release_result(
    engine: SimEngine,
    *,
    segment: RuntimeSegmentState,
    segment_key: str,
    resource_id: str,
    release_result: Any,
    now: float,
    core_id: str,
    reason_override: str | None = None,
) -> None:
    payload = {"segment_key": segment_key, **release_result.metadata}
    if reason_override:
        payload["reason"] = reason_override
    engine._event_bus.publish(
        event_type=EventType.RESOURCE_RELEASE,
        time=now,
        correlation_id=segment.job_id,
        job_id=segment.job_id,
        segment_id=segment.segment_id,
        core_id=core_id,
        resource_id=resource_id,
        payload=payload,
    )
    for woken_segment_key in release_result.woken:
        woken_segment = engine._segments.get(woken_segment_key)
        if woken_segment is None or woken_segment.finished:
            continue
        if woken_segment.job_id in engine._aborted_jobs:
            continue
        woken_segment.blocked = False
        woken_segment.waiting_resource = None
        engine._ready.add(woken_segment_key)
        engine._event_bus.publish(
            event_type=EventType.SEGMENT_UNBLOCKED,
            time=now,
            correlation_id=woken_segment.job_id,
            job_id=woken_segment.job_id,
            segment_id=woken_segment.segment_id,
            core_id=core_id,
            resource_id=resource_id,
            payload={"segment_key": woken_segment_key},
        )
