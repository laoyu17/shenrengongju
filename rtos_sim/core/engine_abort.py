"""Abort-path helpers for ``SimEngine``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rtos_sim.events import EventType
from rtos_sim.model import RuntimeSegmentState
from rtos_sim.protocols import IResourceProtocol

if TYPE_CHECKING:
    from .engine import SimEngine


def abort_job(
    engine: SimEngine,
    job_id: str,
    now: float,
    *,
    preempt_reason: str = "abort_on_miss",
) -> None:
    if job_id in engine._aborted_jobs:
        return
    engine._aborted_jobs.add(job_id)

    segment_keys = [
        segment_key
        for segment_key in engine._segments
        if segment_key.startswith(f"{job_id}:")
    ]
    segment_protocols: dict[str, list[IResourceProtocol]] = {}
    segment_release_cores: dict[str, str | None] = {}
    segment_released_resources: dict[str, list[str]] = {}
    for segment_key in segment_keys:
        segment = engine._segments.get(segment_key)
        if segment is None:
            continue
        segment_protocols[segment_key] = protocols_for_segment(engine, segment)
        segment_release_cores[segment_key] = segment.running_on
        segment_released_resources[segment_key] = sorted(engine._held_resources.get(segment_key, set()))

    for core in engine._cores.values():
        if core.running_segment_key and core.running_segment_key.startswith(f"{job_id}:"):
            engine._apply_preempt(
                core.core_id,
                now,
                force=True,
                requeue=False,
                reason=preempt_reason,
                clear_running_on=True,
            )

    for segment_key in segment_keys:
        segment = engine._segments.get(segment_key)
        if segment is None:
            continue
        segment.blocked = False
        segment.waiting_resource = None
        segment.running_on = None
        engine._ready.discard(segment_key)
        engine._pending_segment_ready_times.pop(segment_key, None)

    for segment_key in segment_keys:
        for protocol in segment_protocols.get(segment_key, []):
            cancel_result = protocol.cancel_segment(segment_key)
            if cancel_result.priority_updates:
                engine._apply_priority_updates(cancel_result.priority_updates)
            for woken_segment_key in cancel_result.woken:
                woken_segment = engine._segments.get(woken_segment_key)
                if woken_segment is None or woken_segment.finished:
                    continue
                if woken_segment.job_id in engine._aborted_jobs:
                    continue
                blocked_resource = woken_segment.waiting_resource
                woken_segment.blocked = False
                woken_segment.waiting_resource = None
                engine._ready.add(woken_segment_key)
                engine._event_bus.publish(
                    event_type=EventType.SEGMENT_UNBLOCKED,
                    time=now,
                    correlation_id=woken_segment.job_id,
                    job_id=woken_segment.job_id,
                    segment_id=woken_segment.segment_id,
                    resource_id=blocked_resource,
                    payload={
                        "segment_key": woken_segment_key,
                        "reason": "cancel_segment",
                        **cancel_result.metadata,
                    },
                )
        segment = engine._segments.get(segment_key)
        for resource_id in segment_released_resources.get(segment_key, []):
            engine._event_bus.publish(
                event_type=EventType.RESOURCE_RELEASE,
                time=now,
                correlation_id=segment.job_id if segment is not None else job_id,
                job_id=segment.job_id if segment is not None else job_id,
                segment_id=segment.segment_id if segment is not None else None,
                core_id=engine._resource_bound_cores.get(
                    resource_id,
                    segment_release_cores.get(segment_key),
                ),
                resource_id=resource_id,
                payload={
                    "segment_key": segment_key,
                    "reason": "cancel_segment",
                },
            )

    for segment_key in segment_keys:
        segment = engine._segments.get(segment_key)
        if segment is not None:
            segment.finished = True
        engine._held_resources[segment_key] = set()
    engine._unregister_active_job_priority(job_id)


def protocols_for_segment(
    engine: SimEngine,
    segment: RuntimeSegmentState,
) -> list[IResourceProtocol]:
    unique: dict[int, IResourceProtocol] = {}
    for resource_id in segment.required_resources:
        protocol = engine._resource_protocols.get(resource_id)
        if protocol is None and engine._protocol is not None:
            protocol = engine._protocol
        if protocol is not None:
            unique[id(protocol)] = protocol
    return list(unique.values())
