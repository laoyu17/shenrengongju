"""Runtime progression helpers for ``SimEngine``."""

from __future__ import annotations

from typing import TYPE_CHECKING
import heapq

from rtos_sim.events import EventType
from rtos_sim.model import CoreState, DecisionAction, ReadySegment, ScheduleSnapshot
from .engine_static_window import (
    apply_static_window_constraints as apply_static_window_constraints_impl,
    enforce_static_window_before_schedule as enforce_static_window_before_schedule_impl,
)

if TYPE_CHECKING:
    from .engine import SimEngine


def advance_once(engine: SimEngine, horizon: float) -> bool:
    assert engine._scheduler and engine._etm and engine._overheads

    now = engine._env.now
    engine._process_releases(now)
    engine._process_segment_ready_heap(now)
    engine._check_deadline_miss(now)
    now = engine._schedule_until_stable(now)

    next_times: list[float] = []
    if engine._release_heap:
        next_times.append(engine._release_heap[0][0])
    if engine._segment_ready_heap:
        next_times.append(engine._segment_ready_heap[0][0])
    for core in engine._cores.values():
        if core.finish_time is not None:
            next_times.append(core.finish_time)
    for job_runtime in engine._jobs.values():
        state = job_runtime.state
        if state.completed or state.missed_deadline or state.absolute_deadline is None:
            continue
        if state.absolute_deadline > now + 1e-12:
            next_times.append(state.absolute_deadline + engine.DEADLINE_EPSILON)
    if not next_times:
        return False

    next_time = min(next_times)
    if next_time <= now + 1e-12:
        next_time = now + 1e-9
    next_time = min(next_time, horizon)

    timeout = engine._env.timeout(next_time - now)
    engine._env.run(until=timeout)

    now = engine._env.now
    engine._process_segment_ready_heap(now)
    engine._check_deadline_miss(now)
    engine._complete_finished_segments(now)
    return True


def process_segment_ready_heap(engine: SimEngine, now: float) -> None:
    while engine._segment_ready_heap and engine._segment_ready_heap[0][0] <= now + 1e-12:
        ready_time, segment_key = heapq.heappop(engine._segment_ready_heap)
        pending = engine._pending_segment_ready_times.get(segment_key)
        if pending is None:
            continue
        if abs(pending - ready_time) > 1e-12:
            continue
        engine._pending_segment_ready_times.pop(segment_key, None)
        engine._mark_segment_ready(segment_key, max(now, ready_time))


def schedule_until_stable(engine: SimEngine, now: float) -> float:
    schedule_now = now
    for _ in range(engine.SCHEDULE_RETRY_LIMIT):
        schedule_now, changed = engine._schedule(schedule_now)
        if schedule_now > now + 1e-12:
            break
        if not changed:
            break
        if not engine._ready:
            break
    else:
        if engine._ready and not any(core.running_segment_key for core in engine._cores.values()):
            engine._event_bus.publish(
                event_type=EventType.ERROR,
                time=schedule_now,
                correlation_id="engine",
                payload={
                    "reason": "schedule_retry_limit",
                    "limit": engine.SCHEDULE_RETRY_LIMIT,
                    "ready_count": len(engine._ready),
                },
            )
    return schedule_now


def build_snapshot(engine: SimEngine, now: float) -> ScheduleSnapshot:
    ready_segments: list[ReadySegment] = []
    for segment_key in engine._ready:
        segment = engine._segments[segment_key]
        if segment.finished or segment.job_id in engine._aborted_jobs:
            continue
        ready_segments.append(
            ReadySegment(
                job_id=segment.job_id,
                task_id=segment.task_id,
                subtask_id=segment.subtask_id,
                segment_id=segment.segment_id,
                remaining_time=segment.remaining_time,
                absolute_deadline=segment.absolute_deadline,
                task_period=segment.task_period,
                mapping_hint=segment.mapping_hint,
                required_resources=list(segment.required_resources),
                preemptible=segment.preemptible,
                release_time=segment.release_time,
                release_index=segment.release_index,
                priority_value=segment.effective_priority,
            )
        )

    core_states: list[CoreState] = []
    for core in engine._cores.values():
        running_segment_key = core.running_segment_key
        running_segment = None
        if running_segment_key:
            segment = engine._segments[running_segment_key]
            if segment.job_id not in engine._aborted_jobs and not segment.finished:
                running_segment = ReadySegment(
                    job_id=segment.job_id,
                    task_id=segment.task_id,
                    subtask_id=segment.subtask_id,
                    segment_id=segment.segment_id,
                    remaining_time=segment.remaining_time,
                    absolute_deadline=segment.absolute_deadline,
                    task_period=segment.task_period,
                    mapping_hint=segment.mapping_hint,
                    required_resources=list(segment.required_resources),
                    preemptible=segment.preemptible,
                    release_time=segment.release_time,
                    priority_value=segment.effective_priority,
                )
            else:
                running_segment_key = None
        core_states.append(
            CoreState(
                core_id=core.core_id,
                core_speed=core.speed,
                running_segment_key=running_segment_key,
                running_since=core.running_since if running_segment_key else None,
                running_segment=running_segment,
            )
        )
    return ScheduleSnapshot(now=now, ready_segments=ready_segments, core_states=core_states)


def schedule(engine: SimEngine, now: float) -> tuple[float, bool]:
    assert engine._scheduler and engine._overheads

    engine._ready = {
        segment_key
        for segment_key in engine._ready
        if segment_key in engine._segments
        and not engine._segments[segment_key].finished
        and engine._segments[segment_key].job_id not in engine._aborted_jobs
    }
    if not engine._ready and not any(core.running_segment_key for core in engine._cores.values()):
        return now, False

    boundary_changed = enforce_static_window_before_schedule_impl(engine, now)
    decisions = engine._scheduler.schedule(now, engine._build_snapshot(now))
    decisions = apply_static_window_constraints_impl(engine, now, decisions)
    schedule_cost = engine._overheads.on_schedule(engine._scheduler.__class__.__name__)
    if schedule_cost > 0:
        timeout = engine._env.timeout(schedule_cost)
        engine._env.run(until=timeout)
        now = engine._env.now

    changed = boundary_changed
    for decision in decisions:
        if decision.action == DecisionAction.PREEMPT and decision.from_core:
            if engine._apply_preempt(decision.from_core, now):
                changed = True

    for decision in decisions:
        if decision.action == DecisionAction.MIGRATE and decision.from_core and decision.to_core:
            source_core = engine._cores.get(decision.from_core)
            if (
                source_core is None
                or source_core.running_segment_key is None
                or (decision.segment_id and source_core.running_segment_key != decision.segment_id)
            ):
                continue
            if engine._apply_preempt(
                decision.from_core,
                now,
                reason="migrate",
                clear_running_on=False,
            ):
                changed = True

    for decision in decisions:
        if decision.action == DecisionAction.DISPATCH and decision.to_core and decision.job_id:
            outcome = engine._apply_dispatch(decision.job_id, decision.segment_id, decision.to_core, now)
            if outcome != "noop":
                changed = True
    return now, changed


def check_deadline_miss(engine: SimEngine, now: float) -> None:
    for job_runtime in engine._jobs.values():
        state = job_runtime.state
        if state.completed or state.missed_deadline or state.absolute_deadline is None:
            continue
        if now <= state.absolute_deadline + 1e-12:
            continue

        state.missed_deadline = True
        engine._event_bus.publish(
            event_type=EventType.DEADLINE_MISS,
            time=now,
            correlation_id=state.job_id,
            job_id=state.job_id,
            payload={
                "absolute_deadline": state.absolute_deadline,
                "abort_on_miss": job_runtime.task.abort_on_miss,
            },
        )

        if job_runtime.task.abort_on_miss:
            engine._abort_job(state.job_id, now)


def finalize_running_segments(engine: SimEngine, *, truncate_running: bool = False) -> None:
    now = engine._env.now
    if truncate_running:
        engine._truncate_running_segments(now)
    engine._check_deadline_miss(now)


def truncate_running_segments(engine: SimEngine, now: float) -> None:
    assert engine._etm
    for core in engine._cores.values():
        segment_key = core.running_segment_key
        if segment_key is None:
            continue
        segment = engine._segments.get(segment_key)
        if segment is None or segment.finished:
            core.running_segment_key = None
            core.running_since = None
            core.finish_time = None
            continue

        if core.running_since is not None:
            elapsed = max(0.0, now - core.running_since)
            executed = elapsed * core.speed
            segment.remaining_time = max(0.0, segment.remaining_time - executed)
            engine._etm.on_exec(segment_key, core.core_id, elapsed)

        segment.finished = True
        segment.running_on = None
        engine._event_bus.publish(
            event_type=EventType.SEGMENT_END,
            time=now,
            correlation_id=segment.job_id,
            job_id=segment.job_id,
            segment_id=segment.segment_id,
            core_id=core.core_id,
            payload={
                "segment_key": segment_key,
                "ended_by": "horizon",
                "truncated": True,
            },
        )
        engine._release_segment_resources(segment, segment_key, now, core.core_id)

        core.running_segment_key = None
        core.running_since = None
        core.finish_time = None
