"""SimPy-backed simulation engine."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
from typing import Callable, Optional

import simpy

from rtos_sim.etm import IExecutionTimeModel, create_etm
from rtos_sim.events import EventBus, EventType, SimEvent
from rtos_sim.metrics import CoreMetrics, IMetric
from rtos_sim.model import (
    CoreState,
    DecisionAction,
    JobState,
    ModelSpec,
    ReadySegment,
    RuntimeSegmentState,
    ScheduleSnapshot,
    TaskGraphSpec,
)
from rtos_sim.overheads import IOverheadModel, create_overhead_model
from rtos_sim.protocols import IResourceProtocol, ResourceRuntimeSpec, create_protocol
from rtos_sim.schedulers import IScheduler, ScheduleContext, create_scheduler

from .interfaces import ISimEngine


@dataclass(slots=True)
class CoreRuntime:
    core_id: str
    speed: float
    running_segment_key: Optional[str] = None
    running_since: Optional[float] = None
    finish_time: Optional[float] = None


@dataclass(slots=True)
class SubtaskRuntime:
    subtask_id: str
    predecessors: list[str]
    successors: list[str]
    segment_keys: list[str]
    next_index: int = 0
    completed: bool = False


@dataclass(slots=True)
class JobRuntime:
    state: JobState
    task: TaskGraphSpec
    subtasks: dict[str, SubtaskRuntime]


class SimEngine(ISimEngine):
    """Discrete-event engine using SimPy clock progression."""

    DEFAULT_EVENT_ID_MODE = "deterministic"
    DEADLINE_EPSILON = 1e-9

    def __init__(
        self,
        scheduler: IScheduler | None = None,
        protocol: IResourceProtocol | None = None,
        etm: IExecutionTimeModel | None = None,
        overhead_model: IOverheadModel | None = None,
        metrics: list[IMetric] | None = None,
    ) -> None:
        self._external_scheduler = scheduler
        self._external_protocol = protocol
        self._external_etm = etm
        self._external_overhead = overhead_model
        self._metrics = metrics or [CoreMetrics()]
        self._subscribers: list[Callable[[SimEvent], None]] = []
        self._event_id_mode = self.DEFAULT_EVENT_ID_MODE
        self._event_id_seed: int | None = None

        self._env = simpy.Environment()
        self._event_bus = self._create_event_bus()
        self._events: list[SimEvent] = []
        self._setup_event_pipeline()

        self._spec: ModelSpec | None = None
        self._scheduler: IScheduler | None = None
        self._protocol: IResourceProtocol | None = None
        self._resource_protocols: dict[str, IResourceProtocol] = {}
        self._etm: IExecutionTimeModel | None = None
        self._overheads: IOverheadModel | None = None

        self._cores: dict[str, CoreRuntime] = {}
        self._segments: dict[str, RuntimeSegmentState] = {}
        self._jobs: dict[str, JobRuntime] = {}
        self._ready: set[str] = set()
        self._held_resources: dict[str, set[str]] = {}
        self._release_heap: list[tuple[float, int, str]] = []
        self._segment_to_subtask: dict[str, tuple[str, str]] = {}
        self._aborted_jobs: set[str] = set()

        self._paused = False
        self._stopped = False

    def subscribe(self, handler: Callable[[SimEvent], None]) -> None:
        if handler in self._subscribers:
            return
        self._subscribers.append(handler)
        self._event_bus.subscribe(handler)

    def build(self, spec: ModelSpec) -> None:
        event_id_mode = spec.scheduler.params.get("event_id_mode", self.DEFAULT_EVENT_ID_MODE)
        if isinstance(event_id_mode, str) and event_id_mode.strip():
            self._event_id_mode = event_id_mode.strip().lower()
        else:
            self._event_id_mode = self.DEFAULT_EVENT_ID_MODE
        self._event_id_seed = spec.sim.seed
        self.reset()
        self._spec = spec

        self._scheduler = self._external_scheduler or create_scheduler(
            spec.scheduler.name,
            spec.scheduler.params,
        )
        self._scheduler.init(ScheduleContext(core_ids=[core.id for core in spec.platform.cores]))

        self._setup_protocols(spec)

        etm_name = str(spec.scheduler.params.get("etm", "default"))
        self._etm = self._external_etm or create_etm(etm_name)

        overhead_name = str(spec.scheduler.params.get("overhead_model", "default"))
        overhead_params = spec.scheduler.params.get("overhead", {})
        if not isinstance(overhead_params, dict):
            overhead_params = {}
        self._overheads = self._external_overhead or create_overhead_model(overhead_name, overhead_params)

        self._cores = {
            core.id: CoreRuntime(core_id=core.id, speed=core.speed_factor)
            for core in spec.platform.cores
        }

        for task in spec.tasks:
            heapq.heappush(self._release_heap, (task.arrival, 0, task.id))

    def run(self, until: float | None = None) -> None:
        if self._spec is None:
            raise RuntimeError("build() must be called before run()")
        horizon = until if until is not None else self._spec.sim.duration

        while self._env.now < horizon and not self._stopped:
            if self._paused:
                break
            progressed = self._advance_once(horizon)
            if not progressed:
                break

        self._finalize_running_segments()

    def step(self, delta: float | None = None) -> None:
        if self._spec is None:
            raise RuntimeError("build() must be called before step()")
        target = self._env.now + (delta if delta is not None else 0.0)
        if delta is None:
            self._advance_once(self._spec.sim.duration)
        else:
            while self._env.now < target and not self._stopped:
                progressed = self._advance_once(target)
                if not progressed:
                    break

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def stop(self) -> None:
        self._stopped = True

    def reset(self) -> None:
        self._env = simpy.Environment()
        for metric in self._metrics:
            metric.reset()
        self._event_bus = self._create_event_bus()
        self._events = []
        self._setup_event_pipeline()

        self._spec = None
        self._scheduler = None
        self._protocol = None
        self._resource_protocols = {}
        self._etm = None
        self._overheads = None
        self._cores = {}
        self._segments = {}
        self._jobs = {}
        self._ready = set()
        self._held_resources = {}
        self._release_heap = []
        self._segment_to_subtask = {}
        self._aborted_jobs = set()
        self._paused = False
        self._stopped = False

    def _setup_event_pipeline(self) -> None:
        self._event_bus.subscribe(self._events.append)
        for metric in self._metrics:
            self._event_bus.subscribe(metric.consume)
        for handler in self._subscribers:
            self._event_bus.subscribe(handler)

    @property
    def events(self) -> list[SimEvent]:
        return list(self._events)

    def metric_report(self) -> dict:
        merged: dict = {}
        for metric in self._metrics:
            merged.update(metric.report())
        core_utilization = merged.get("core_utilization")
        if isinstance(core_utilization, dict):
            for core_id in self._cores:
                core_utilization.setdefault(core_id, 0.0)
        return merged

    def _create_event_bus(self) -> EventBus:
        return EventBus(
            event_id_mode=self._event_id_mode,
            event_id_seed=self._event_id_seed,
        )

    def _setup_protocols(self, spec: ModelSpec) -> None:
        resource_specs = self._build_resource_runtime_specs(spec)
        self._resource_protocols = {}

        if self._external_protocol is not None:
            self._protocol = self._external_protocol
            self._protocol.configure(resource_specs)
            for resource_id in resource_specs:
                self._resource_protocols[resource_id] = self._protocol
            return

        if not spec.resources:
            self._protocol = create_protocol("mutex")
            self._protocol.configure({})
            return

        grouped: dict[str, dict[str, ResourceRuntimeSpec]] = {}
        for resource in spec.resources:
            grouped.setdefault(resource.protocol.lower(), {})[resource.id] = resource_specs[resource.id]

        self._protocol = None
        for protocol_name, protocol_resources in grouped.items():
            protocol = create_protocol(protocol_name)
            protocol.configure(protocol_resources)
            if self._protocol is None:
                self._protocol = protocol
            for resource_id in protocol_resources:
                self._resource_protocols[resource_id] = protocol

        if self._protocol is None:
            self._protocol = create_protocol("mutex")
            self._protocol.configure({})

    def _build_resource_runtime_specs(self, spec: ModelSpec) -> dict[str, ResourceRuntimeSpec]:
        resource_ceilings: dict[str, float] = {
            resource.id: self._lowest_priority_value() for resource in spec.resources
        }
        for task in spec.tasks:
            task_priority = self._task_priority_value(task.deadline, task.period)
            for subtask in task.subtasks:
                for segment in subtask.segments:
                    for resource_id in segment.required_resources:
                        if resource_id in resource_ceilings:
                            resource_ceilings[resource_id] = max(resource_ceilings[resource_id], task_priority)

        runtime_specs: dict[str, ResourceRuntimeSpec] = {}
        for resource in spec.resources:
            ceiling = resource_ceilings.get(resource.id, self._lowest_priority_value())
            if ceiling <= self._lowest_priority_value() + 1e-6:
                ceiling = 0.0
            runtime_specs[resource.id] = ResourceRuntimeSpec(
                bound_core_id=resource.bound_core_id,
                ceiling_priority=ceiling,
            )
        return runtime_specs

    def _protocol_for_resource(self, resource_id: str) -> IResourceProtocol:
        protocol = self._resource_protocols.get(resource_id)
        if protocol is not None:
            return protocol
        if self._protocol is None:
            raise RuntimeError("resource protocol not initialized")
        return self._protocol

    def _lowest_priority_value(self) -> float:
        return -1e18

    def _task_priority_value(self, deadline: float | None, period: float | None) -> float:
        if self._spec is None:
            return 0.0
        scheduler_name = self._spec.scheduler.name.lower()
        if scheduler_name in {"edf", "earliest_deadline_first"}:
            if deadline is None:
                return self._lowest_priority_value()
            return -float(deadline)
        if scheduler_name in {"rm", "rate_monotonic", "fixed_priority"}:
            if period is None:
                return self._lowest_priority_value()
            return -float(period)
        return 0.0

    def _apply_priority_updates(self, updates: dict[str, float]) -> None:
        for segment_key, effective_priority in updates.items():
            segment = self._segments.get(segment_key)
            if segment is None or segment.finished:
                continue
            segment.effective_priority = float(effective_priority)

    def _advance_once(self, horizon: float) -> bool:
        assert self._scheduler and self._etm and self._overheads

        now = self._env.now
        self._process_releases(now)
        self._check_deadline_miss(now)
        self._schedule(now)

        next_times: list[float] = []
        if self._release_heap:
            next_times.append(self._release_heap[0][0])
        for core in self._cores.values():
            if core.finish_time is not None:
                next_times.append(core.finish_time)
        for job_runtime in self._jobs.values():
            state = job_runtime.state
            if state.completed or state.missed_deadline or state.absolute_deadline is None:
                continue
            if state.absolute_deadline > now + 1e-12:
                next_times.append(state.absolute_deadline + self.DEADLINE_EPSILON)

        if not next_times:
            # Some dispatch attempts may block immediately and leave the core idle
            # while ready segments still exist. Re-schedule once before stopping.
            if self._ready:
                self._schedule(now)
                for core in self._cores.values():
                    if core.finish_time is not None:
                        next_times.append(core.finish_time)
            if not next_times:
                return False

        next_time = min(next_times)
        if next_time <= now + 1e-12:
            next_time = now + 1e-9
        next_time = min(next_time, horizon)

        timeout = self._env.timeout(next_time - now)
        self._env.run(until=timeout)

        now = self._env.now
        self._check_deadline_miss(now)
        self._complete_finished_segments(now)
        return True

    def _process_releases(self, now: float) -> None:
        assert self._spec and self._scheduler

        while self._release_heap and self._release_heap[0][0] <= now + 1e-12:
            release_time, release_idx, task_id = heapq.heappop(self._release_heap)
            task = next(t for t in self._spec.tasks if t.id == task_id)
            job_id = f"{task.id}@{release_idx}"
            absolute_deadline = release_time + task.deadline if task.deadline is not None else None
            base_priority = self._task_priority_value(absolute_deadline, task.period)
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
                    self._segments[segment_key] = RuntimeSegmentState(
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
                    )
                    self._segment_to_subtask[segment_key] = (job_id, sub.id)
                    self._held_resources[segment_key] = set()
                    segment_keys.append(segment_key)

                subtasks[sub.id] = SubtaskRuntime(
                    subtask_id=sub.id,
                    predecessors=list(sub.predecessors),
                    successors=list(sub.successors),
                    segment_keys=segment_keys,
                )

            self._jobs[job_id] = JobRuntime(state=job_state, task=task, subtasks=subtasks)

            self._event_bus.publish(
                event_type=EventType.JOB_RELEASED,
                time=now,
                correlation_id=job_id,
                job_id=job_id,
                payload={
                    "task_id": task.id,
                    "release_index": release_idx,
                    "absolute_deadline": absolute_deadline,
                },
            )
            self._scheduler.on_release(job_id)

            for subtask in subtasks.values():
                if not subtask.predecessors:
                    self._mark_segment_ready(subtask.segment_keys[0], now)

            # Schedule next release if periodic.
            if task.period is not None:
                next_idx = release_idx + 1
                next_release = task.arrival + task.period * next_idx
                if self._spec and next_release <= self._spec.sim.duration + 1e-12:
                    heapq.heappush(self._release_heap, (next_release, next_idx, task.id))

    def _mark_segment_ready(self, segment_key: str, now: float) -> None:
        segment = self._segments[segment_key]
        if segment.finished or segment.job_id in self._aborted_jobs:
            return
        segment.blocked = False
        segment.waiting_resource = None
        self._ready.add(segment_key)
        self._scheduler.on_segment_ready(segment_key)
        self._event_bus.publish(
            event_type=EventType.SEGMENT_READY,
            time=now,
            correlation_id=segment.job_id,
            job_id=segment.job_id,
            segment_id=segment.segment_id,
            payload={"segment_key": segment.key, "subtask_id": segment.subtask_id},
        )

    def _build_snapshot(self, now: float) -> ScheduleSnapshot:
        ready_segments: list[ReadySegment] = []
        for segment_key in self._ready:
            segment = self._segments[segment_key]
            if segment.finished or segment.job_id in self._aborted_jobs:
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
                    priority_value=segment.effective_priority,
                )
            )

        core_states: list[CoreState] = []
        for core in self._cores.values():
            running_segment_key = core.running_segment_key
            running_segment = None
            if running_segment_key:
                segment = self._segments[running_segment_key]
                if segment.job_id not in self._aborted_jobs and not segment.finished:
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

    def _schedule(self, now: float) -> None:
        assert self._scheduler and self._overheads

        self._ready = {
            segment_key
            for segment_key in self._ready
            if segment_key in self._segments
            and not self._segments[segment_key].finished
            and self._segments[segment_key].job_id not in self._aborted_jobs
        }
        if not self._ready and not any(core.running_segment_key for core in self._cores.values()):
            return

        decisions = self._scheduler.schedule(now, self._build_snapshot(now))
        schedule_cost = self._overheads.on_schedule(self._scheduler.__class__.__name__)
        if schedule_cost > 0:
            timeout = self._env.timeout(schedule_cost)
            self._env.run(until=timeout)
            now = self._env.now

        for decision in decisions:
            if decision.action == DecisionAction.PREEMPT and decision.from_core:
                self._apply_preempt(decision.from_core, now)

        for decision in decisions:
            if decision.action == DecisionAction.MIGRATE and decision.from_core and decision.to_core:
                self._event_bus.publish(
                    event_type=EventType.MIGRATE,
                    time=now,
                    correlation_id=decision.job_id or "",
                    job_id=decision.job_id,
                    segment_id=decision.segment_id,
                    core_id=decision.to_core,
                    payload={
                        "from_core": decision.from_core,
                        "to_core": decision.to_core,
                        "reason": decision.reason,
                    },
                )

        for decision in decisions:
            if decision.action == DecisionAction.DISPATCH and decision.to_core and decision.job_id:
                self._apply_dispatch(decision.job_id, decision.segment_id, decision.to_core, now)

    def _apply_preempt(
        self,
        core_id: str,
        now: float,
        *,
        force: bool = False,
        requeue: bool = True,
        reason: str | None = None,
    ) -> bool:
        core = self._cores[core_id]
        if not core.running_segment_key:
            return False
        segment = self._segments[core.running_segment_key]
        if not segment.preemptible and not force:
            return False
        if core.running_since is not None:
            elapsed = max(0.0, now - core.running_since)
            executed = elapsed * core.speed
            segment.remaining_time = max(0.0, segment.remaining_time - executed)
        segment.running_on = None

        if requeue and not segment.finished and segment.job_id not in self._aborted_jobs:
            self._ready.add(segment.key)
        payload = {"segment_key": segment.key}
        if reason:
            payload["reason"] = reason
        self._event_bus.publish(
            event_type=EventType.PREEMPT,
            time=now,
            correlation_id=segment.job_id,
            job_id=segment.job_id,
            segment_id=segment.segment_id,
            core_id=core_id,
            payload=payload,
        )
        core.running_segment_key = None
        core.running_since = None
        core.finish_time = None
        return True

    def _apply_dispatch(self, job_id: str, decision_segment_id: str | None, core_id: str, now: float) -> None:
        assert self._etm and self._overheads

        if job_id in self._aborted_jobs:
            return
        core = self._cores[core_id]
        if core.running_segment_key is not None:
            return

        candidates = [
            key
            for key in self._ready
            if key.startswith(f"{job_id}:")
            and (
                decision_segment_id is None
                or decision_segment_id in (key, self._segments[key].segment_id)
            )
        ]
        if not candidates:
            return

        segment_key = sorted(candidates)[0]
        segment = self._segments[segment_key]
        if segment.finished or segment.job_id in self._aborted_jobs:
            self._ready.discard(segment_key)
            return

        for resource_id in segment.required_resources:
            if resource_id in self._held_resources[segment_key]:
                continue
            protocol = self._protocol_for_resource(resource_id)
            request_priority = segment.effective_priority
            result = protocol.request(segment_key, resource_id, core_id, request_priority)
            if result.priority_updates:
                self._apply_priority_updates(result.priority_updates)
            if not result.granted:
                segment.blocked = True
                segment.waiting_resource = resource_id
                self._ready.discard(segment_key)
                self._event_bus.publish(
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
                        **result.metadata,
                    },
                )
                return
            self._held_resources[segment_key].add(resource_id)
            self._event_bus.publish(
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
        if segment.running_on and segment.running_on != core_id:
            migration_cost = self._overheads.on_migration(segment.job_id, segment.running_on, core_id)

        context_cost = self._overheads.on_context_switch(segment.job_id, core_id)
        execution_time = self._etm.estimate(segment.remaining_time, core.speed, now)
        total_runtime = migration_cost + context_cost + execution_time

        segment.running_on = core_id
        if segment.started_at is None:
            segment.started_at = now
        segment.blocked = False

        self._ready.discard(segment_key)
        core.running_segment_key = segment_key
        core.running_since = now
        core.finish_time = now + total_runtime

        self._event_bus.publish(
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
            },
        )

    def _complete_finished_segments(self, now: float) -> None:
        finished_cores = [
            core
            for core in self._cores.values()
            if core.running_segment_key and core.finish_time is not None and core.finish_time <= now + 1e-9
        ]
        for core in finished_cores:
            segment_key = core.running_segment_key
            if segment_key is None:
                continue
            segment = self._segments[segment_key]
            if core.running_since is not None:
                elapsed = max(0.0, now - core.running_since)
                executed = elapsed * core.speed
                segment.remaining_time = max(0.0, segment.remaining_time - executed)
                self._etm.on_exec(segment_key, core.core_id, elapsed)

            segment.finished = True
            segment.running_on = None

            self._event_bus.publish(
                event_type=EventType.SEGMENT_END,
                time=now,
                correlation_id=segment.job_id,
                job_id=segment.job_id,
                segment_id=segment.segment_id,
                core_id=core.core_id,
                payload={"segment_key": segment_key},
            )

            for resource_id in sorted(self._held_resources.get(segment_key, set())):
                protocol = self._protocol_for_resource(resource_id)
                release_result = protocol.release(segment_key, resource_id)
                if release_result.priority_updates:
                    self._apply_priority_updates(release_result.priority_updates)
                self._event_bus.publish(
                    event_type=EventType.RESOURCE_RELEASE,
                    time=now,
                    correlation_id=segment.job_id,
                    job_id=segment.job_id,
                    segment_id=segment.segment_id,
                    core_id=core.core_id,
                    resource_id=resource_id,
                    payload={"segment_key": segment_key, **release_result.metadata},
                )
                for woken_segment_key in release_result.woken:
                    woken_segment = self._segments[woken_segment_key]
                    if woken_segment.finished or woken_segment.job_id in self._aborted_jobs:
                        continue
                    woken_segment.blocked = False
                    woken_segment.waiting_resource = None
                    self._ready.add(woken_segment_key)
                    self._event_bus.publish(
                        event_type=EventType.SEGMENT_UNBLOCKED,
                        time=now,
                        correlation_id=woken_segment.job_id,
                        job_id=woken_segment.job_id,
                        segment_id=woken_segment.segment_id,
                        core_id=core.core_id,
                        resource_id=resource_id,
                        payload={"segment_key": woken_segment_key},
                    )

            self._held_resources[segment_key] = set()
            self._on_segment_finish(segment_key, now)

            core.running_segment_key = None
            core.running_since = None
            core.finish_time = None

    def _on_segment_finish(self, segment_key: str, now: float) -> None:
        segment = self._segments[segment_key]
        if segment.job_id in self._aborted_jobs:
            return
        job_runtime = self._jobs[segment.job_id]
        subtask = job_runtime.subtasks[segment.subtask_id]
        subtask.next_index += 1

        if subtask.next_index < len(subtask.segment_keys):
            self._mark_segment_ready(subtask.segment_keys[subtask.next_index], now)
            return

        subtask.completed = True
        job_runtime.state.subtask_completion[subtask.subtask_id] = True

        for successor_id in subtask.successors:
            successor = job_runtime.subtasks[successor_id]
            if successor.completed:
                continue
            if all(job_runtime.state.subtask_completion[pred] for pred in successor.predecessors):
                self._mark_segment_ready(successor.segment_keys[0], now)

        if all(job_runtime.state.subtask_completion.values()):
            job_runtime.state.completed = True
            self._scheduler.on_complete(segment.job_id)
            self._event_bus.publish(
                event_type=EventType.JOB_COMPLETE,
                time=now,
                correlation_id=segment.job_id,
                job_id=segment.job_id,
                payload={"task_id": segment.task_id},
            )

    def _check_deadline_miss(self, now: float) -> None:
        for job_runtime in self._jobs.values():
            state = job_runtime.state
            if state.completed or state.missed_deadline or state.absolute_deadline is None:
                continue
            if now <= state.absolute_deadline + 1e-12:
                continue

            state.missed_deadline = True
            self._event_bus.publish(
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
                self._abort_job(state.job_id, now)

    def _abort_job(self, job_id: str, now: float) -> None:
        if job_id in self._aborted_jobs:
            return
        self._aborted_jobs.add(job_id)

        segment_keys = [
            segment_key
            for segment_key in self._segments
            if segment_key.startswith(f"{job_id}:")
        ]
        segment_protocols: dict[str, list[IResourceProtocol]] = {}
        for segment_key in segment_keys:
            segment = self._segments.get(segment_key)
            if segment is None:
                continue
            segment_protocols[segment_key] = self._protocols_for_segment(segment)

        for core in self._cores.values():
            if core.running_segment_key and core.running_segment_key.startswith(f"{job_id}:"):
                self._apply_preempt(
                    core.core_id,
                    now,
                    force=True,
                    requeue=False,
                    reason="abort_on_miss",
                )

        for segment_key in segment_keys:
            segment = self._segments.get(segment_key)
            if segment is None:
                continue
            segment.blocked = False
            segment.waiting_resource = None
            segment.running_on = None
            self._ready.discard(segment_key)

        for segment_key in segment_keys:
            for protocol in segment_protocols.get(segment_key, []):
                cancel_result = protocol.cancel_segment(segment_key)
                if cancel_result.priority_updates:
                    self._apply_priority_updates(cancel_result.priority_updates)
                for woken_segment_key in cancel_result.woken:
                    woken_segment = self._segments.get(woken_segment_key)
                    if woken_segment is None or woken_segment.finished:
                        continue
                    if woken_segment.job_id in self._aborted_jobs:
                        continue
                    woken_segment.blocked = False
                    woken_segment.waiting_resource = None
                    self._ready.add(woken_segment_key)

        for segment_key in segment_keys:
            segment = self._segments.get(segment_key)
            if segment is not None:
                segment.finished = True
            self._held_resources[segment_key] = set()

    def _protocols_for_segment(self, segment: RuntimeSegmentState) -> list[IResourceProtocol]:
        unique: dict[int, IResourceProtocol] = {}
        for resource_id in segment.required_resources:
            protocol = self._resource_protocols.get(resource_id)
            if protocol is None and self._protocol is not None:
                protocol = self._protocol
            if protocol is not None:
                unique[id(protocol)] = protocol
        return list(unique.values())

    def _finalize_running_segments(self) -> None:
        # Keep deterministic reports when run() exits early.
        now = self._env.now
        self._check_deadline_miss(now)
