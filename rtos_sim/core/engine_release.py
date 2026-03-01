"""Release-path helpers for ``SimEngine``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
import heapq

from rtos_sim.arrival import IArrivalGenerator, create_arrival_generator
from rtos_sim.events import EventType
from rtos_sim.model import JobState, RuntimeSegmentState, TaskGraphSpec

if TYPE_CHECKING:
    from .engine import SimEngine


def process_releases(engine: SimEngine, now: float) -> None:
    from .engine import JobRuntime, SubtaskRuntime

    assert engine._spec and engine._scheduler

    while engine._release_heap and engine._release_heap[0][0] <= now + 1e-12:
        release_time, release_idx, task_id = heapq.heappop(engine._release_heap)
        task = next(t for t in engine._spec.tasks if t.id == task_id)
        job_id = f"{task.id}@{release_idx}"
        absolute_deadline = release_time + task.deadline if task.deadline is not None else None
        base_priority = engine._task_priority_value(absolute_deadline, task.period)
        subtask_completion = {sub.id: False for sub in task.subtasks}
        job_state = JobState(
            task_id=task.id,
            job_id=job_id,
            release_time=release_time,
            absolute_deadline=absolute_deadline,
            subtask_completion=subtask_completion,
        )

        subtasks: dict[str, SubtaskRuntime] = {}
        for sub in task.subtasks:
            segment_keys: list[str] = []
            for seg in sorted(sub.segments, key=lambda s: s.index):
                segment_key = f"{job_id}:{sub.id}:{seg.id}"
                deterministic_ready_time, deterministic_window_id, deterministic_offset_index = (
                    engine._resolve_deterministic_ready_info(
                        task=task,
                        release_idx=release_idx,
                        release_time=release_time,
                        release_offsets=seg.release_offsets,
                    )
                )
                engine._segments[segment_key] = RuntimeSegmentState(
                    task_id=task.id,
                    job_id=job_id,
                    subtask_id=sub.id,
                    segment_id=seg.id,
                    wcet=seg.wcet,
                    remaining_time=seg.wcet,
                    required_resources=list(seg.required_resources),
                    mapping_hint=seg.mapping_hint,
                    preemptible=seg.preemptible,
                    absolute_deadline=absolute_deadline,
                    task_period=task.period,
                    release_time=release_time,
                    predecessor_subtasks=list(sub.predecessors),
                    successor_subtasks=list(sub.successors),
                    segment_index=seg.index,
                    base_priority=base_priority,
                    effective_priority=base_priority,
                    deterministic_ready_time=deterministic_ready_time,
                    deterministic_window_id=deterministic_window_id,
                    deterministic_offset_index=deterministic_offset_index,
                )
                engine._segment_to_subtask[segment_key] = (job_id, sub.id)
                engine._held_resources[segment_key] = set()
                segment_keys.append(segment_key)

            subtasks[sub.id] = SubtaskRuntime(
                subtask_id=sub.id,
                predecessors=list(sub.predecessors),
                successors=list(sub.successors),
                segment_keys=segment_keys,
            )

        engine._jobs[job_id] = JobRuntime(state=job_state, task=task, subtasks=subtasks)
        engine._register_active_job_priority(job_id, base_priority)

        engine._event_bus.publish(
            event_type=EventType.JOB_RELEASED,
            time=now,
            correlation_id=job_id,
            job_id=job_id,
            payload={
                "task_id": task.id,
                "release_index": release_idx,
                "absolute_deadline": absolute_deadline,
                "deterministic_hyper_period": engine._deterministic_hyper_period,
            },
        )
        engine._scheduler.on_release(job_id)

        for subtask in subtasks.values():
            if not subtask.predecessors:
                engine._queue_segment_ready(subtask.segment_keys[0], now)

        next_idx = release_idx + 1
        next_release = engine._next_release_time(task, next_idx, release_time)
        if next_release is not None and engine._spec and next_release <= engine._spec.sim.duration + 1e-12:
            heapq.heappush(engine._release_heap, (next_release, next_idx, task.id))


def resolve_deterministic_ready_info(
    engine: SimEngine,
    *,
    task: TaskGraphSpec,
    release_idx: int,
    release_time: float,
    release_offsets: list[float] | None,
) -> tuple[float | None, int | None, int | None]:
    if task.task_type.value != "time_deterministic":
        return None, None, None
    offsets = release_offsets or [0.0]
    offset_index = release_idx % len(offsets)
    ready_time = release_time + offsets[offset_index]
    base_release = engine._release_base_time(task)
    window_id = release_idx
    hyper_period = engine._deterministic_hyper_period
    if hyper_period is not None and hyper_period > 1e-12:
        elapsed = max(0.0, release_time - base_release)
        window_id = int((elapsed + 1e-12) // hyper_period)
    return ready_time, window_id, offset_index


def next_release_time(
    engine: SimEngine,
    task: TaskGraphSpec,
    release_idx: int,
    current_release: float,
) -> float | None:
    arrival_process = task.arrival_process
    if arrival_process is not None:
        if arrival_process.max_releases is not None and release_idx >= arrival_process.max_releases:
            return None

        process_type = arrival_process.type.value
        params = arrival_process.params
        if process_type == "one_shot":
            return None

        if process_type == "fixed":
            interval = resolve_arrival_interval(
                params.get("interval"),
                fallback=task.min_inter_arrival if task.min_inter_arrival is not None else task.period,
            )
            if interval is None:
                raise ValueError("arrival_process type=fixed requires interval")
            return current_release + interval

        if process_type == "uniform":
            lower = resolve_arrival_interval(
                params.get("min_interval"),
                fallback=task.min_inter_arrival if task.min_inter_arrival is not None else task.period,
            )
            upper = resolve_arrival_interval(
                params.get("max_interval"),
                fallback=task.max_inter_arrival,
            )
            if lower is None or upper is None:
                raise ValueError("arrival_process type=uniform requires min_interval and max_interval")
            if upper < lower - 1e-12:
                raise ValueError("arrival_process uniform max_interval must be >= min_interval")
            return current_release + engine._arrival_rng.uniform(lower, upper)

        if process_type == "poisson":
            rate = resolve_arrival_interval(params.get("rate"))
            if rate is None:
                raise ValueError("arrival_process type=poisson requires rate")
            return current_release + engine._arrival_rng.expovariate(rate)

        if process_type == "custom":
            generator_name = params.get("generator")
            if not isinstance(generator_name, str) or not generator_name.strip():
                raise ValueError("arrival_process type=custom requires params.generator")
            generator = resolve_arrival_generator(engine, generator_name)
            interval = generator.next_interval(
                task=task,
                now=engine._env.now,
                current_release=current_release,
                release_index=release_idx,
                params=dict(params),
                rng=engine._arrival_rng,
            )
            if not isinstance(interval, (int, float)):
                raise ValueError("custom arrival generator must return numeric interval")
            resolved_interval = float(interval)
            if resolved_interval <= 0:
                raise ValueError("custom arrival generator interval must be > 0")
            return current_release + resolved_interval

        raise ValueError(f"unsupported arrival_process type: {process_type}")

    if task.task_type.value == "time_deterministic":
        if task.period is None:
            return None
        phase_offset = task.phase_offset or 0.0
        return task.arrival + phase_offset + task.period * release_idx
    if task.task_type.value == "dynamic_rt":
        interval = task.min_inter_arrival if task.min_inter_arrival is not None else task.period
        if interval is None:
            return None
        arrival_model = (
            task.arrival_model.value
            if task.arrival_model is not None
            else ("uniform_interval" if task.max_inter_arrival is not None else "fixed_interval")
        )
        if arrival_model == "uniform_interval":
            upper_bound = task.max_inter_arrival if task.max_inter_arrival is not None else interval
            interval = engine._arrival_rng.uniform(interval, upper_bound)
        elif arrival_model != "fixed_interval":
            raise ValueError(f"unsupported dynamic arrival model: {arrival_model}")
        if interval <= 0:
            raise ValueError("computed dynamic release interval must be > 0")
        return current_release + interval
    return None


def resolve_arrival_interval(raw: Any, *, fallback: float | None = None) -> float | None:
    value = raw if raw is not None else fallback
    if value is None:
        return None
    resolved = float(value)
    if resolved <= 0:
        raise ValueError("computed dynamic release interval must be > 0")
    return resolved


def resolve_arrival_generator(engine: SimEngine, name: str) -> IArrivalGenerator:
    key = name.strip().lower()
    if key not in engine._arrival_generators:
        engine._arrival_generators[key] = create_arrival_generator(key)
    return engine._arrival_generators[key]


def queue_segment_ready(engine: SimEngine, segment_key: str, now: float) -> None:
    segment = engine._segments[segment_key]
    if segment.finished or segment.job_id in engine._aborted_jobs:
        return
    ready_time = segment.deterministic_ready_time
    if ready_time is None or ready_time <= now + 1e-12:
        engine._mark_segment_ready(segment_key, now if ready_time is None else max(now, ready_time))
        return
    pending = engine._pending_segment_ready_times.get(segment_key)
    if pending is not None and pending <= ready_time + 1e-12:
        return
    engine._pending_segment_ready_times[segment_key] = ready_time
    heapq.heappush(engine._segment_ready_heap, (ready_time, segment_key))


def mark_segment_ready(engine: SimEngine, segment_key: str, now: float) -> None:
    segment = engine._segments[segment_key]
    if segment.finished or segment.job_id in engine._aborted_jobs:
        return
    segment.blocked = False
    segment.waiting_resource = None
    engine._pending_segment_ready_times.pop(segment_key, None)
    engine._ready.add(segment_key)
    engine._scheduler.on_segment_ready(segment_key)
    payload: dict[str, Any] = {"segment_key": segment.key, "subtask_id": segment.subtask_id}
    if segment.deterministic_window_id is not None:
        payload["deterministic_window_id"] = segment.deterministic_window_id
    if segment.deterministic_offset_index is not None:
        payload["deterministic_offset_index"] = segment.deterministic_offset_index
    if segment.deterministic_ready_time is not None:
        payload["deterministic_ready_time"] = segment.deterministic_ready_time
    engine._event_bus.publish(
        event_type=EventType.SEGMENT_READY,
        time=now,
        correlation_id=segment.job_id,
        job_id=segment.job_id,
        segment_id=segment.segment_id,
        payload=payload,
    )
