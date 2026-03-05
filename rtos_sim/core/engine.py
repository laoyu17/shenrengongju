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

from .engine_abort import abort_job as abort_job_impl, protocols_for_segment as protocols_for_segment_impl
from .engine_dispatch import (
    apply_dispatch as apply_dispatch_impl,
    on_resource_release_result as on_resource_release_result_impl,
    rollback_dispatch_resources as rollback_dispatch_resources_impl,
)
from .engine_release import (
    mark_segment_ready as mark_segment_ready_impl,
    next_release_time as next_release_time_impl,
    process_releases as process_releases_impl,
    queue_segment_ready as queue_segment_ready_impl,
    resolve_arrival_generator as resolve_arrival_generator_impl,
    resolve_arrival_interval as resolve_arrival_interval_impl,
    resolve_deterministic_ready_info as resolve_deterministic_ready_info_impl,
)
from .engine_runtime import (
    advance_once as advance_once_impl,
    build_snapshot as build_snapshot_impl,
    check_deadline_miss as check_deadline_miss_impl,
    finalize_running_segments as finalize_running_segments_impl,
    process_segment_ready_heap as process_segment_ready_heap_impl,
    schedule as schedule_impl,
    schedule_until_stable as schedule_until_stable_impl,
    truncate_running_segments as truncate_running_segments_impl,
)
from .engine_static_window import configure_static_window_mode as configure_static_window_mode_impl
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
        self._static_window_mode_enabled = False
        self._static_windows_by_core: dict[str, list] = {}

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
        self._tasks_by_id: dict[str, TaskGraphSpec] = {}
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
        self._tasks_by_id = {task.id: task for task in spec.tasks}

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
        configure_static_window_mode_impl(self, spec)
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
        self._static_window_mode_enabled = False
        self._static_windows_by_core = {}

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
        self._tasks_by_id = {}
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
        return advance_once_impl(self, horizon)

    def _process_segment_ready_heap(self, now: float) -> None:
        process_segment_ready_heap_impl(self, now)

    def _schedule_until_stable(self, now: float) -> float:
        return schedule_until_stable_impl(self, now)

    def _process_releases(self, now: float) -> None:
        process_releases_impl(self, now)

    def _resolve_deterministic_ready_info(
        self,
        *,
        task: TaskGraphSpec,
        release_idx: int,
        release_time: float,
        release_offsets: list[float] | None,
    ) -> tuple[float | None, int | None, int | None]:
        return resolve_deterministic_ready_info_impl(
            self,
            task=task,
            release_idx=release_idx,
            release_time=release_time,
            release_offsets=release_offsets,
        )

    def _next_release_time(self, task: TaskGraphSpec, release_idx: int, current_release: float) -> float | None:
        return next_release_time_impl(self, task, release_idx, current_release)

    @staticmethod
    def _resolve_arrival_interval(raw: Any, *, fallback: float | None = None) -> float | None:
        return resolve_arrival_interval_impl(raw, fallback=fallback)

    def _resolve_arrival_generator(self, name: str) -> IArrivalGenerator:
        return resolve_arrival_generator_impl(self, name)

    def _queue_segment_ready(self, segment_key: str, now: float) -> None:
        queue_segment_ready_impl(self, segment_key, now)

    def _mark_segment_ready(self, segment_key: str, now: float) -> None:
        mark_segment_ready_impl(self, segment_key, now)

    def _build_snapshot(self, now: float) -> ScheduleSnapshot:
        return build_snapshot_impl(self, now)

    def _schedule(self, now: float) -> tuple[float, bool]:
        return schedule_impl(self, now)

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
        return apply_dispatch_impl(self, job_id, decision_segment_id, core_id, now)

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
        return rollback_dispatch_resources_impl(
            self,
            segment=segment,
            segment_key=segment_key,
            resource_ids=resource_ids,
            now=now,
            core_id=core_id,
        )

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
        on_resource_release_result_impl(
            self,
            segment=segment,
            segment_key=segment_key,
            resource_id=resource_id,
            release_result=release_result,
            now=now,
            core_id=core_id,
            reason_override=reason_override,
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
        check_deadline_miss_impl(self, now)

    def _abort_job(self, job_id: str, now: float, *, preempt_reason: str = "abort_on_miss") -> None:
        abort_job_impl(self, job_id, now, preempt_reason=preempt_reason)

    def _protocols_for_segment(self, segment: RuntimeSegmentState) -> list[IResourceProtocol]:
        return protocols_for_segment_impl(self, segment)

    def _finalize_running_segments(self, *, truncate_running: bool = False) -> None:
        finalize_running_segments_impl(self, truncate_running=truncate_running)

    def _truncate_running_segments(self, now: float) -> None:
        truncate_running_segments_impl(self, now)
