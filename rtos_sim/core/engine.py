"""SimPy-backed simulation engine."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import heapq
from math import gcd
import random
from typing import Any, Callable, Optional

import simpy

from rtos_sim.arrival import IArrivalGenerator, create_arrival_generator
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
    DEFAULT_RESOURCE_ACQUIRE_POLICY = "legacy_sequential"
    VALID_EVENT_ID_MODES = {"deterministic", "random", "seeded_random"}
    VALID_RESOURCE_ACQUIRE_POLICIES = {"legacy_sequential", "atomic_rollback"}
    DEADLINE_EPSILON = 1e-9
    SCHEDULE_RETRY_LIMIT = 8

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
        self._arrival_rng = random.Random(0)
        self._arrival_generators: dict[str, IArrivalGenerator] = {}
        self._resource_acquire_policy = self.DEFAULT_RESOURCE_ACQUIRE_POLICY

        self._env = simpy.Environment()
        self._event_bus = self._create_event_bus()
        self._events: list[SimEvent] = []
        self._setup_event_pipeline()

        self._spec: ModelSpec | None = None
        self._scheduler: IScheduler | None = None
        self._protocol: IResourceProtocol | None = None
        self._resource_protocols: dict[str, IResourceProtocol] = {}
        self._protocol_resources: dict[IResourceProtocol, set[str]] = {}
        self._resource_bound_cores: dict[str, str] = {}
        self._etm: IExecutionTimeModel | None = None
        self._overheads: IOverheadModel | None = None

        self._cores: dict[str, CoreRuntime] = {}
        self._segments: dict[str, RuntimeSegmentState] = {}
        self._jobs: dict[str, JobRuntime] = {}
        self._ready: set[str] = set()
        self._held_resources: dict[str, set[str]] = {}
        self._release_heap: list[tuple[float, int, str]] = []
        self._segment_ready_heap: list[tuple[float, str]] = []
        self._pending_segment_ready_times: dict[str, float] = {}
        self._segment_to_subtask: dict[str, tuple[str, str]] = {}
        self._aborted_jobs: set[str] = set()
        self._deterministic_hyper_period: float | None = None
        self._task_resource_usage: dict[str, set[str]] = {}
        self._active_job_priorities: dict[str, float] = {}

        self._paused = False
        self._stopped = False

    def subscribe(self, handler: Callable[[SimEvent], None]) -> None:
        if handler in self._subscribers:
            return
        self._subscribers.append(handler)
        self._event_bus.subscribe(handler)

    def build(self, spec: ModelSpec) -> None:
        self._event_id_mode = self._resolve_event_id_mode(spec.scheduler.params)
        self._event_id_seed = spec.sim.seed
        self.reset()
        self._arrival_rng = random.Random(spec.sim.seed)
        self._resource_acquire_policy = self._resolve_resource_acquire_policy(spec.scheduler.params)
        self._spec = spec

        self._scheduler = self._external_scheduler or create_scheduler(
            spec.scheduler.name,
            spec.scheduler.params,
        )
        self._scheduler.init(ScheduleContext(core_ids=[core.id for core in spec.platform.cores]))
        self._task_resource_usage = self._index_task_resource_usage(spec)

        self._setup_protocols(spec)

        etm_name = str(spec.scheduler.params.get("etm", "default"))
        etm_params = spec.scheduler.params.get("etm_params", {})
        if not isinstance(etm_params, dict):
            etm_params = {}
        self._etm = self._external_etm or create_etm(etm_name, etm_params)

        overhead_name = str(spec.scheduler.params.get("overhead_model", "default"))
        overhead_params = spec.scheduler.params.get("overhead", {})
        if not isinstance(overhead_params, dict):
            overhead_params = {}
        self._overheads = self._external_overhead or create_overhead_model(overhead_name, overhead_params)

        processor_speed_by_type = {processor.id: processor.speed_factor for processor in spec.platform.processor_types}
        self._cores = {}
        for core in spec.platform.cores:
            processor_speed = processor_speed_by_type.get(core.type_id, 1.0)
            effective_speed = core.speed_factor * processor_speed
            self._cores[core.id] = CoreRuntime(core_id=core.id, speed=effective_speed)
        self._deterministic_hyper_period = self._compute_deterministic_hyper_period(spec)

        for task in spec.tasks:
            heapq.heappush(self._release_heap, (self._release_base_time(task), 0, task.id))

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

        reached_horizon = self._env.now >= horizon - 1e-12
        self._finalize_running_segments(truncate_running=reached_horizon and not self._paused and not self._stopped)

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
        self._arrival_rng = random.Random(0)
        self._arrival_generators = {}

        self._spec = None
        self._scheduler = None
        self._protocol = None
        self._resource_protocols = {}
        self._protocol_resources = {}
        self._resource_bound_cores = {}
        self._etm = None
        self._overheads = None
        self._cores = {}
        self._segments = {}
        self._jobs = {}
        self._ready = set()
        self._held_resources = {}
        self._release_heap = []
        self._segment_ready_heap = []
        self._pending_segment_ready_times = {}
        self._segment_to_subtask = {}
        self._aborted_jobs = set()
        self._deterministic_hyper_period = None
        self._task_resource_usage = {}
        self._active_job_priorities = {}
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

    @property
    def now(self) -> float:
        return float(self._env.now)

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
        self._protocol_resources = {}
        self._resource_bound_cores = {
            resource_id: runtime_spec.bound_core_id for resource_id, runtime_spec in resource_specs.items()
        }

        if self._external_protocol is not None:
            self._protocol = self._external_protocol
            self._protocol.configure(resource_specs)
            for resource_id in resource_specs:
                self._resource_protocols[resource_id] = self._protocol
            self._protocol_resources[self._protocol] = set(resource_specs)
            self._configure_protocol_priority_domain(self._protocol)
            self._refresh_runtime_resource_ceilings()
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
            self._configure_protocol_priority_domain(protocol)
            if self._protocol is None:
                self._protocol = protocol
            for resource_id in protocol_resources:
                self._resource_protocols[resource_id] = protocol
                self._protocol_resources.setdefault(protocol, set()).add(resource_id)

        if self._protocol is None:
            self._protocol = create_protocol("mutex")
            self._protocol.configure({})
            self._configure_protocol_priority_domain(self._protocol)
        self._refresh_runtime_resource_ceilings()

    def _build_resource_runtime_specs(self, spec: ModelSpec) -> dict[str, ResourceRuntimeSpec]:
        if self._is_edf_scheduler_name(spec.scheduler.name):
            lowest = self._lowest_priority_value()
            return {
                resource.id: ResourceRuntimeSpec(
                    bound_core_id=resource.bound_core_id,
                    ceiling_priority=lowest,
                )
                for resource in spec.resources
            }
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
            runtime_specs[resource.id] = ResourceRuntimeSpec(
                bound_core_id=resource.bound_core_id,
                ceiling_priority=ceiling,
            )
        return runtime_specs

    @staticmethod
    def _index_task_resource_usage(spec: ModelSpec) -> dict[str, set[str]]:
        usage: dict[str, set[str]] = {}
        for task in spec.tasks:
            task_resources: set[str] = set()
            for subtask in task.subtasks:
                for segment in subtask.segments:
                    task_resources.update(segment.required_resources)
            usage[task.id] = task_resources
        return usage

    @staticmethod
    def _is_edf_scheduler_name(name: str) -> bool:
        scheduler_name = str(name).strip().lower()
        return scheduler_name in {"edf", "earliest_deadline_first"}

    def _is_edf_scheduler(self) -> bool:
        if self._spec is None:
            return False
        return self._is_edf_scheduler_name(self._spec.scheduler.name)

    def _configure_protocol_priority_domain(self, protocol: IResourceProtocol) -> None:
        if self._is_edf_scheduler():
            protocol.set_priority_domain("absolute_deadline")
            return
        protocol.set_priority_domain("fixed_priority")

    def _refresh_runtime_resource_ceilings(self) -> None:
        if not self._is_edf_scheduler() or not self._protocol_resources:
            return
        lowest = self._lowest_priority_value()
        ceilings = {resource_id: lowest for resource_id in self._resource_protocols}
        for job_id, priority_value in self._active_job_priorities.items():
            job_runtime = self._jobs.get(job_id)
            if job_runtime is None:
                continue
            for resource_id in self._task_resource_usage.get(job_runtime.state.task_id, set()):
                if resource_id in ceilings:
                    ceilings[resource_id] = max(ceilings[resource_id], priority_value)

        for protocol, resource_ids in self._protocol_resources.items():
            protocol.update_resource_ceilings(
                {
                    resource_id: ceilings.get(resource_id, 0.0)
                    for resource_id in resource_ids
                }
            )

    def _register_active_job_priority(self, job_id: str, priority_value: float) -> None:
        self._active_job_priorities[job_id] = float(priority_value)
        self._refresh_runtime_resource_ceilings()

    def _unregister_active_job_priority(self, job_id: str) -> None:
        if job_id not in self._active_job_priorities:
            return
        self._active_job_priorities.pop(job_id, None)
        self._refresh_runtime_resource_ceilings()

    def _protocol_for_resource(self, resource_id: str) -> IResourceProtocol:
        protocol = self._resource_protocols.get(resource_id)
        if protocol is not None:
            return protocol
        if self._protocol is None:
            raise RuntimeError("resource protocol not initialized")
        return self._protocol

    def _resolve_event_id_mode(self, params: dict[str, Any]) -> str:
        mode_raw = params.get("event_id_mode", self.DEFAULT_EVENT_ID_MODE)
        mode = str(mode_raw).strip().lower() if mode_raw is not None else ""
        if not mode:
            return self.DEFAULT_EVENT_ID_MODE
        if mode in self.VALID_EVENT_ID_MODES:
            return mode

        raise ValueError(
            "invalid scheduler.params.event_id_mode='"
            f"{mode_raw}', expected deterministic|random|seeded_random"
        )

    def _resolve_resource_acquire_policy(self, params: dict[str, Any]) -> str:
        policy_raw = params.get("resource_acquire_policy", self.DEFAULT_RESOURCE_ACQUIRE_POLICY)
        policy = str(policy_raw).strip().lower() if policy_raw is not None else ""
        if not policy:
            return self.DEFAULT_RESOURCE_ACQUIRE_POLICY
        if policy not in self.VALID_RESOURCE_ACQUIRE_POLICIES:
            raise ValueError(
                "scheduler.params.resource_acquire_policy must be one of "
                "legacy_sequential|atomic_rollback"
            )
        return policy

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

    @staticmethod
    def _lcm(lhs: int, rhs: int) -> int:
        return lhs * rhs // gcd(lhs, rhs)

    def _compute_deterministic_hyper_period(self, spec: ModelSpec) -> float | None:
        periods = [
            task.period
            for task in spec.tasks
            if task.task_type.value == "time_deterministic" and task.period is not None
        ]
        if not periods:
            return None
        fractions = [Fraction(str(period)).limit_denominator(1_000_000) for period in periods]
        denominator_lcm = 1
        for value in fractions:
            denominator_lcm = self._lcm(denominator_lcm, value.denominator)
        numerators: list[int] = []
        for value in fractions:
            numerators.append(value.numerator * (denominator_lcm // value.denominator))
        numerator_lcm = 1
        for value in numerators:
            numerator_lcm = self._lcm(numerator_lcm, value)
        return float(Fraction(numerator_lcm, denominator_lcm))

    @staticmethod
    def _release_base_time(task: TaskGraphSpec) -> float:
        phase_offset = task.phase_offset or 0.0
        if task.task_type.value == "time_deterministic":
            return task.arrival + phase_offset
        return task.arrival

    def _advance_once(self, horizon: float) -> bool:
        assert self._scheduler and self._etm and self._overheads

        now = self._env.now
        self._process_releases(now)
        self._process_segment_ready_heap(now)
        self._check_deadline_miss(now)
        now = self._schedule_until_stable(now)

        next_times: list[float] = []
        if self._release_heap:
            next_times.append(self._release_heap[0][0])
        if self._segment_ready_heap:
            next_times.append(self._segment_ready_heap[0][0])
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
            return False

        next_time = min(next_times)
        if next_time <= now + 1e-12:
            next_time = now + 1e-9
        next_time = min(next_time, horizon)

        timeout = self._env.timeout(next_time - now)
        self._env.run(until=timeout)

        now = self._env.now
        self._process_segment_ready_heap(now)
        self._check_deadline_miss(now)
        self._complete_finished_segments(now)
        return True

    def _process_segment_ready_heap(self, now: float) -> None:
        while self._segment_ready_heap and self._segment_ready_heap[0][0] <= now + 1e-12:
            ready_time, segment_key = heapq.heappop(self._segment_ready_heap)
            pending = self._pending_segment_ready_times.get(segment_key)
            if pending is None:
                continue
            if abs(pending - ready_time) > 1e-12:
                continue
            self._pending_segment_ready_times.pop(segment_key, None)
            self._mark_segment_ready(segment_key, max(now, ready_time))

    def _schedule_until_stable(self, now: float) -> float:
        schedule_now = now
        for _ in range(self.SCHEDULE_RETRY_LIMIT):
            schedule_now, changed = self._schedule(schedule_now)
            if schedule_now > now + 1e-12:
                break
            if not changed:
                break
            if not self._ready:
                break
        else:
            if self._ready and not any(core.running_segment_key for core in self._cores.values()):
                self._event_bus.publish(
                    event_type=EventType.ERROR,
                    time=schedule_now,
                    correlation_id="engine",
                    payload={
                        "reason": "schedule_retry_limit",
                        "limit": self.SCHEDULE_RETRY_LIMIT,
                        "ready_count": len(self._ready),
                    },
                )
        return schedule_now

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
                    deterministic_ready_time, deterministic_window_id, deterministic_offset_index = (
                        self._resolve_deterministic_ready_info(
                            task=task,
                            release_idx=release_idx,
                            release_time=release_time,
                            release_offsets=seg.release_offsets,
                        )
                    )
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
                        deterministic_ready_time=deterministic_ready_time,
                        deterministic_window_id=deterministic_window_id,
                        deterministic_offset_index=deterministic_offset_index,
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
            self._register_active_job_priority(job_id, base_priority)

            self._event_bus.publish(
                event_type=EventType.JOB_RELEASED,
                time=now,
                correlation_id=job_id,
                job_id=job_id,
                payload={
                    "task_id": task.id,
                    "release_index": release_idx,
                    "absolute_deadline": absolute_deadline,
                    "deterministic_hyper_period": self._deterministic_hyper_period,
                },
            )
            self._scheduler.on_release(job_id)

            for subtask in subtasks.values():
                if not subtask.predecessors:
                    self._queue_segment_ready(subtask.segment_keys[0], now)

            next_idx = release_idx + 1
            next_release = self._next_release_time(task, next_idx, release_time)
            if next_release is not None and self._spec and next_release <= self._spec.sim.duration + 1e-12:
                heapq.heappush(self._release_heap, (next_release, next_idx, task.id))

    def _resolve_deterministic_ready_info(
        self,
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
        base_release = self._release_base_time(task)
        window_id = release_idx
        hyper_period = self._deterministic_hyper_period
        if hyper_period is not None and hyper_period > 1e-12:
            elapsed = max(0.0, release_time - base_release)
            window_id = int((elapsed + 1e-12) // hyper_period)
        return ready_time, window_id, offset_index

    def _next_release_time(self, task: TaskGraphSpec, release_idx: int, current_release: float) -> float | None:
        arrival_process = task.arrival_process
        if arrival_process is not None:
            if arrival_process.max_releases is not None and release_idx >= arrival_process.max_releases:
                return None

            process_type = arrival_process.type.value
            params = arrival_process.params
            if process_type == "one_shot":
                return None

            if process_type == "fixed":
                interval = self._resolve_arrival_interval(
                    params.get("interval"),
                    fallback=task.min_inter_arrival if task.min_inter_arrival is not None else task.period,
                )
                if interval is None:
                    raise ValueError("arrival_process type=fixed requires interval")
                return current_release + interval

            if process_type == "uniform":
                lower = self._resolve_arrival_interval(
                    params.get("min_interval"),
                    fallback=task.min_inter_arrival if task.min_inter_arrival is not None else task.period,
                )
                upper = self._resolve_arrival_interval(
                    params.get("max_interval"),
                    fallback=task.max_inter_arrival,
                )
                if lower is None or upper is None:
                    raise ValueError("arrival_process type=uniform requires min_interval and max_interval")
                if upper < lower - 1e-12:
                    raise ValueError("arrival_process uniform max_interval must be >= min_interval")
                return current_release + self._arrival_rng.uniform(lower, upper)

            if process_type == "poisson":
                rate = self._resolve_arrival_interval(params.get("rate"))
                if rate is None:
                    raise ValueError("arrival_process type=poisson requires rate")
                return current_release + self._arrival_rng.expovariate(rate)

            if process_type == "custom":
                generator_name = params.get("generator")
                if not isinstance(generator_name, str) or not generator_name.strip():
                    raise ValueError("arrival_process type=custom requires params.generator")
                generator = self._resolve_arrival_generator(generator_name)
                interval = generator.next_interval(
                    task=task,
                    now=self._env.now,
                    current_release=current_release,
                    release_index=release_idx,
                    params=dict(params),
                    rng=self._arrival_rng,
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
                interval = self._arrival_rng.uniform(interval, upper_bound)
            elif arrival_model != "fixed_interval":
                raise ValueError(f"unsupported dynamic arrival model: {arrival_model}")
            if interval <= 0:
                raise ValueError("computed dynamic release interval must be > 0")
            return current_release + interval
        return None

    @staticmethod
    def _resolve_arrival_interval(raw: Any, *, fallback: float | None = None) -> float | None:
        value = raw if raw is not None else fallback
        if value is None:
            return None
        resolved = float(value)
        if resolved <= 0:
            raise ValueError("computed dynamic release interval must be > 0")
        return resolved

    def _resolve_arrival_generator(self, name: str) -> IArrivalGenerator:
        key = name.strip().lower()
        if key not in self._arrival_generators:
            self._arrival_generators[key] = create_arrival_generator(key)
        return self._arrival_generators[key]

    def _queue_segment_ready(self, segment_key: str, now: float) -> None:
        segment = self._segments[segment_key]
        if segment.finished or segment.job_id in self._aborted_jobs:
            return
        ready_time = segment.deterministic_ready_time
        if ready_time is None or ready_time <= now + 1e-12:
            self._mark_segment_ready(segment_key, now if ready_time is None else max(now, ready_time))
            return
        pending = self._pending_segment_ready_times.get(segment_key)
        if pending is not None and pending <= ready_time + 1e-12:
            return
        self._pending_segment_ready_times[segment_key] = ready_time
        heapq.heappush(self._segment_ready_heap, (ready_time, segment_key))

    def _mark_segment_ready(self, segment_key: str, now: float) -> None:
        segment = self._segments[segment_key]
        if segment.finished or segment.job_id in self._aborted_jobs:
            return
        segment.blocked = False
        segment.waiting_resource = None
        self._pending_segment_ready_times.pop(segment_key, None)
        self._ready.add(segment_key)
        self._scheduler.on_segment_ready(segment_key)
        payload: dict[str, Any] = {"segment_key": segment.key, "subtask_id": segment.subtask_id}
        if segment.deterministic_window_id is not None:
            payload["deterministic_window_id"] = segment.deterministic_window_id
        if segment.deterministic_offset_index is not None:
            payload["deterministic_offset_index"] = segment.deterministic_offset_index
        if segment.deterministic_ready_time is not None:
            payload["deterministic_ready_time"] = segment.deterministic_ready_time
        self._event_bus.publish(
            event_type=EventType.SEGMENT_READY,
            time=now,
            correlation_id=segment.job_id,
            job_id=segment.job_id,
            segment_id=segment.segment_id,
            payload=payload,
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

    def _schedule(self, now: float) -> tuple[float, bool]:
        assert self._scheduler and self._overheads

        self._ready = {
            segment_key
            for segment_key in self._ready
            if segment_key in self._segments
            and not self._segments[segment_key].finished
            and self._segments[segment_key].job_id not in self._aborted_jobs
        }
        if not self._ready and not any(core.running_segment_key for core in self._cores.values()):
            return now, False

        decisions = self._scheduler.schedule(now, self._build_snapshot(now))
        schedule_cost = self._overheads.on_schedule(self._scheduler.__class__.__name__)
        if schedule_cost > 0:
            timeout = self._env.timeout(schedule_cost)
            self._env.run(until=timeout)
            now = self._env.now

        changed = False
        for decision in decisions:
            if decision.action == DecisionAction.PREEMPT and decision.from_core:
                if self._apply_preempt(decision.from_core, now):
                    changed = True

        for decision in decisions:
            if decision.action == DecisionAction.MIGRATE and decision.from_core and decision.to_core:
                source_core = self._cores.get(decision.from_core)
                if (
                    source_core is None
                    or source_core.running_segment_key is None
                    or (decision.segment_id and source_core.running_segment_key != decision.segment_id)
                ):
                    continue
                if self._apply_preempt(
                    decision.from_core,
                    now,
                    reason="migrate",
                    clear_running_on=False,
                ):
                    changed = True

        for decision in decisions:
            if decision.action == DecisionAction.DISPATCH and decision.to_core and decision.job_id:
                outcome = self._apply_dispatch(decision.job_id, decision.segment_id, decision.to_core, now)
                if outcome != "noop":
                    changed = True
        return now, changed

    def _apply_preempt(
        self,
        core_id: str,
        now: float,
        *,
        force: bool = False,
        requeue: bool = True,
        reason: str | None = None,
        clear_running_on: bool = False,
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
        if clear_running_on:
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

    def _apply_dispatch(self, job_id: str, decision_segment_id: str | None, core_id: str, now: float) -> str:
        assert self._etm and self._overheads

        if job_id in self._aborted_jobs:
            return "noop"
        core = self._cores[core_id]
        if core.running_segment_key is not None:
            return "noop"

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
            return "noop"

        segment_key = sorted(candidates)[0]
        segment = self._segments[segment_key]
        if segment.finished or segment.job_id in self._aborted_jobs:
            self._ready.discard(segment_key)
            return "dropped"
        if segment.mapping_hint is not None and segment.mapping_hint != core_id:
            self._event_bus.publish(
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
            self._abort_job(segment.job_id, now, preempt_reason="abort_on_error")
            return "error"

        acquired_resources_this_dispatch: list[str] = []
        for resource_id in segment.required_resources:
            if resource_id in self._held_resources[segment_key]:
                continue
            protocol = self._protocol_for_resource(resource_id)
            request_priority = segment.effective_priority
            result = protocol.request(segment_key, resource_id, core_id, request_priority)
            if result.priority_updates:
                self._apply_priority_updates(result.priority_updates)
            if not result.granted:
                rollback_released: list[str] = []
                if (
                    self._resource_acquire_policy == "atomic_rollback"
                    and acquired_resources_this_dispatch
                    and result.reason != "bound_core_violation"
                ):
                    rollback_released = self._rollback_dispatch_resources(
                        segment=segment,
                        segment_key=segment_key,
                        resource_ids=acquired_resources_this_dispatch,
                        now=now,
                        core_id=core_id,
                    )
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
                        "resource_acquire_policy": self._resource_acquire_policy,
                        "rollback_applied": bool(rollback_released),
                        "rollback_released_resources": sorted(rollback_released),
                        **result.metadata,
                    },
                )
                if result.reason == "bound_core_violation":
                    self._event_bus.publish(
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
                    self._abort_job(segment.job_id, now, preempt_reason="abort_on_error")
                    return "error"
                return "blocked"
            self._held_resources[segment_key].add(resource_id)
            acquired_resources_this_dispatch.append(resource_id)
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
        previous_core = segment.running_on
        if previous_core and previous_core != core_id:
            migration_cost = self._overheads.on_migration(segment.job_id, previous_core, core_id)
            self._event_bus.publish(
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

        context_cost = self._overheads.on_context_switch(segment.job_id, core_id)
        execution_time = self._etm.estimate(
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
                "deterministic_window_id": segment.deterministic_window_id,
                "deterministic_offset_index": segment.deterministic_offset_index,
            },
        )
        return "started"

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

            self._release_segment_resources(segment, segment_key, now, core.core_id)
            self._on_segment_finish(segment_key, now)

            core.running_segment_key = None
            core.running_since = None
            core.finish_time = None

    def _release_segment_resources(
        self,
        segment: RuntimeSegmentState,
        segment_key: str,
        now: float,
        core_id: str,
    ) -> None:
        for resource_id in sorted(self._held_resources.get(segment_key, set())):
            protocol = self._protocol_for_resource(resource_id)
            release_result = protocol.release(segment_key, resource_id)
            if release_result.priority_updates:
                self._apply_priority_updates(release_result.priority_updates)
            self._on_resource_release_result(
                segment=segment,
                segment_key=segment_key,
                resource_id=resource_id,
                release_result=release_result,
                now=now,
                core_id=core_id,
            )

        self._held_resources[segment_key] = set()

    def _rollback_dispatch_resources(
        self,
        *,
        segment: RuntimeSegmentState,
        segment_key: str,
        resource_ids: list[str],
        now: float,
        core_id: str,
    ) -> list[str]:
        released: list[str] = []
        for resource_id in reversed(resource_ids):
            if resource_id not in self._held_resources.get(segment_key, set()):
                continue
            protocol = self._protocol_for_resource(resource_id)
            release_result = protocol.release(segment_key, resource_id)
            if release_result.priority_updates:
                self._apply_priority_updates(release_result.priority_updates)
            self._on_resource_release_result(
                segment=segment,
                segment_key=segment_key,
                resource_id=resource_id,
                release_result=release_result,
                now=now,
                core_id=core_id,
                reason_override="acquire_rollback",
            )
            self._held_resources[segment_key].discard(resource_id)
            released.append(resource_id)
        return released

    def _on_resource_release_result(
        self,
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
        self._event_bus.publish(
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
            woken_segment = self._segments.get(woken_segment_key)
            if woken_segment is None or woken_segment.finished:
                continue
            if woken_segment.job_id in self._aborted_jobs:
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
                core_id=core_id,
                resource_id=resource_id,
                payload={"segment_key": woken_segment_key},
            )

    def _on_segment_finish(self, segment_key: str, now: float) -> None:
        segment = self._segments[segment_key]
        if segment.job_id in self._aborted_jobs:
            return
        job_runtime = self._jobs[segment.job_id]
        subtask = job_runtime.subtasks[segment.subtask_id]
        subtask.next_index += 1

        if subtask.next_index < len(subtask.segment_keys):
            self._queue_segment_ready(subtask.segment_keys[subtask.next_index], now)
            return

        subtask.completed = True
        job_runtime.state.subtask_completion[subtask.subtask_id] = True

        for successor_id in subtask.successors:
            successor = job_runtime.subtasks[successor_id]
            if successor.completed:
                continue
            if all(job_runtime.state.subtask_completion[pred] for pred in successor.predecessors):
                self._queue_segment_ready(successor.segment_keys[0], now)

        if all(job_runtime.state.subtask_completion.values()):
            job_runtime.state.completed = True
            self._scheduler.on_complete(segment.job_id)
            self._unregister_active_job_priority(segment.job_id)
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

    def _abort_job(self, job_id: str, now: float, *, preempt_reason: str = "abort_on_miss") -> None:
        if job_id in self._aborted_jobs:
            return
        self._aborted_jobs.add(job_id)

        segment_keys = [
            segment_key
            for segment_key in self._segments
            if segment_key.startswith(f"{job_id}:")
        ]
        segment_protocols: dict[str, list[IResourceProtocol]] = {}
        segment_release_cores: dict[str, str | None] = {}
        segment_released_resources: dict[str, list[str]] = {}
        for segment_key in segment_keys:
            segment = self._segments.get(segment_key)
            if segment is None:
                continue
            segment_protocols[segment_key] = self._protocols_for_segment(segment)
            segment_release_cores[segment_key] = segment.running_on
            segment_released_resources[segment_key] = sorted(self._held_resources.get(segment_key, set()))

        for core in self._cores.values():
            if core.running_segment_key and core.running_segment_key.startswith(f"{job_id}:"):
                self._apply_preempt(
                    core.core_id,
                    now,
                    force=True,
                    requeue=False,
                    reason=preempt_reason,
                    clear_running_on=True,
                )

        for segment_key in segment_keys:
            segment = self._segments.get(segment_key)
            if segment is None:
                continue
            segment.blocked = False
            segment.waiting_resource = None
            segment.running_on = None
            self._ready.discard(segment_key)
            self._pending_segment_ready_times.pop(segment_key, None)

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
                    blocked_resource = woken_segment.waiting_resource
                    woken_segment.blocked = False
                    woken_segment.waiting_resource = None
                    self._ready.add(woken_segment_key)
                    self._event_bus.publish(
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
            segment = self._segments.get(segment_key)
            for resource_id in segment_released_resources.get(segment_key, []):
                self._event_bus.publish(
                    event_type=EventType.RESOURCE_RELEASE,
                    time=now,
                    correlation_id=segment.job_id if segment is not None else job_id,
                    job_id=segment.job_id if segment is not None else job_id,
                    segment_id=segment.segment_id if segment is not None else None,
                    core_id=self._resource_bound_cores.get(
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
            segment = self._segments.get(segment_key)
            if segment is not None:
                segment.finished = True
            self._held_resources[segment_key] = set()
        self._unregister_active_job_priority(job_id)

    def _protocols_for_segment(self, segment: RuntimeSegmentState) -> list[IResourceProtocol]:
        unique: dict[int, IResourceProtocol] = {}
        for resource_id in segment.required_resources:
            protocol = self._resource_protocols.get(resource_id)
            if protocol is None and self._protocol is not None:
                protocol = self._protocol
            if protocol is not None:
                unique[id(protocol)] = protocol
        return list(unique.values())

    def _finalize_running_segments(self, *, truncate_running: bool = False) -> None:
        now = self._env.now
        if truncate_running:
            self._truncate_running_segments(now)
        self._check_deadline_miss(now)

    def _truncate_running_segments(self, now: float) -> None:
        assert self._etm
        for core in self._cores.values():
            segment_key = core.running_segment_key
            if segment_key is None:
                continue
            segment = self._segments.get(segment_key)
            if segment is None or segment.finished:
                core.running_segment_key = None
                core.running_since = None
                core.finish_time = None
                continue

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
                payload={
                    "segment_key": segment_key,
                    "ended_by": "horizon",
                    "truncated": True,
                },
            )
            self._release_segment_resources(segment, segment_key, now, core.core_id)

            core.running_segment_key = None
            core.running_since = None
            core.finish_time = None
