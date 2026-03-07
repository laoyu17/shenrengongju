"""Shared semantic normalization for planning/runtime bridging."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import heapq
import json
from random import Random
from typing import Any

from rtos_sim.arrival import create_arrival_generator
from rtos_sim.arrival.builtins import generator_uses_rng, resolve_generator_min_interval
from rtos_sim.etm import create_etm
from rtos_sim.model import (
    ArrivalProcessType,
    ModelSpec,
    TaskGraphSpec,
    TaskType,
)

from .types import normalize_task_scope


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _task_in_scope(task_type: TaskType, scope: str) -> bool:
    if scope == "sync_only":
        return task_type == TaskType.TIME_DETERMINISTIC
    if scope == "sync_and_dynamic_rt":
        return task_type != TaskType.NON_RT
    return True


def _task_arrival_mode(task: TaskGraphSpec) -> str:
    if task.task_type == TaskType.TIME_DETERMINISTIC:
        return "time_deterministic"
    if task.arrival_process is not None:
        return task.arrival_process.type.value
    if task.arrival_model is not None:
        return task.arrival_model.value
    return "legacy_arrival"


class _PlanningArrivalContext:
    def __init__(
        self,
        seed: int,
        *,
        mode: str,
        conservative_min_intervals: dict[str, float] | None = None,
    ) -> None:
        self.rng = Random(seed)
        self.mode = mode
        self.generators: dict[str, Any] = {}
        self.conservative_min_intervals = dict(conservative_min_intervals or {})




def _arrival_analysis_mode(spec: ModelSpec) -> str:
    planning_params = getattr(spec.planning, "params", {}) if spec.planning is not None else {}
    if not isinstance(planning_params, dict):
        planning_params = {}
    raw = planning_params.get("arrival_analysis_mode", "sample_path")
    mode = str(raw or "sample_path").strip().lower()
    if mode not in {"sample_path", "conservative_envelope"}:
        raise ValueError("planning.params.arrival_analysis_mode must be sample_path|conservative_envelope")
    return mode


def _conservative_min_interval_map(spec: ModelSpec) -> dict[str, float]:
    planning_params = getattr(spec.planning, "params", {}) if spec.planning is not None else {}
    if not isinstance(planning_params, dict):
        return {}
    raw = planning_params.get("arrival_envelope_min_intervals", {})
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("planning.params.arrival_envelope_min_intervals must be object")
    result: dict[str, float] = {}
    for task_id, value in raw.items():
        resolved = float(value)
        if resolved <= 0:
            raise ValueError("planning.params.arrival_envelope_min_intervals values must be > 0")
        result[str(task_id)] = resolved
    return result


def _conservative_interval(
    ctx: _PlanningArrivalContext,
    task: TaskGraphSpec,
    *,
    process_type: str | None,
    params: dict[str, Any],
) -> float | None:
    override = ctx.conservative_min_intervals.get(task.id)
    if process_type == "one_shot":
        return None
    if process_type == "fixed":
        return _resolve_positive_interval(
            params.get("interval"),
            fallback=task.min_inter_arrival if task.min_inter_arrival is not None else task.period,
        )
    if process_type == "uniform":
        return _resolve_positive_interval(
            params.get("min_interval"),
            fallback=task.min_inter_arrival if task.min_inter_arrival is not None else task.period,
        )
    if process_type == "poisson":
        if override is not None:
            return override
        raise ValueError(
            f"task '{task.id}' requires planning.params.arrival_envelope_min_intervals.{task.id} "
            "when arrival_analysis_mode=conservative_envelope and arrival_process.type=poisson"
        )
    if process_type == "custom":
        generator_name = str(params.get("generator") or "").strip().lower()
        resolved_interval, _ = resolve_generator_min_interval(generator_name, params)
        if resolved_interval is not None:
            return resolved_interval
        if override is not None:
            return override
        raise ValueError(
            f"task '{task.id}' requires planning.params.arrival_envelope_min_intervals.{task.id} "
            f"when arrival_analysis_mode=conservative_envelope and custom generator '{generator_name or 'unknown'}' has no built-in lower bound"
        )
    if task.task_type == TaskType.TIME_DETERMINISTIC:
        return float(task.period) if task.period is not None else None
    if task.task_type == TaskType.DYNAMIC_RT:
        arrival_model = (
            task.arrival_model.value
            if task.arrival_model is not None
            else ("uniform_interval" if task.max_inter_arrival is not None else "fixed_interval")
        )
        if arrival_model == "fixed_interval":
            return _resolve_positive_interval(task.min_inter_arrival, fallback=task.period)
        if arrival_model == "uniform_interval":
            return _resolve_positive_interval(task.min_inter_arrival, fallback=task.period)
    if override is not None:
        return override
    return None

def _release_base_time(task: TaskGraphSpec) -> float:
    phase_offset = task.phase_offset or 0.0
    if task.task_type == TaskType.TIME_DETERMINISTIC:
        return float(task.arrival + phase_offset)
    return float(task.arrival)


def _resolve_positive_interval(value: Any, *, fallback: float | None = None) -> float | None:
    resolved = value if value is not None else fallback
    if resolved is None:
        return None
    interval = float(resolved)
    if interval <= 0:
        raise ValueError("computed dynamic release interval must be > 0")
    return interval

def _arrival_generator_name(task: TaskGraphSpec) -> str:
    if task.task_type == TaskType.TIME_DETERMINISTIC:
        return "time_deterministic"
    process = task.arrival_process
    if process is not None:
        if process.type == ArrivalProcessType.CUSTOM:
            raw = process.params.get("generator")
            if isinstance(raw, str) and raw.strip():
                return raw.strip().lower()
            return "custom"
        return process.type.value
    if task.task_type == TaskType.DYNAMIC_RT:
        if task.arrival_model is not None:
            return task.arrival_model.value
        return "uniform_interval" if task.max_inter_arrival is not None else "fixed_interval"
    return "legacy_arrival"


def _arrival_trace_seed_source(task: TaskGraphSpec, *, arrival_analysis_mode: str) -> str:
    if task.task_type == TaskType.TIME_DETERMINISTIC:
        return "not_applicable"
    if arrival_analysis_mode != "sample_path":
        return "not_used(conservative_envelope)"
    process = task.arrival_process
    if process is not None:
        if process.type in {ArrivalProcessType.UNIFORM, ArrivalProcessType.POISSON}:
            return "sim.seed"
        if process.type == ArrivalProcessType.CUSTOM:
            return "sim.seed" if generator_uses_rng(_arrival_generator_name(task)) else "not_required"
        return "not_required"
    if task.task_type == TaskType.DYNAMIC_RT:
        return "sim.seed" if _arrival_generator_name(task) == "uniform_interval" else "not_required"
    return "not_applicable"


def _arrival_min_interval_and_source(
    task: TaskGraphSpec,
    *,
    arrival_analysis_mode: str,
    conservative_min_intervals: dict[str, float],
) -> tuple[float | None, str]:
    override = conservative_min_intervals.get(task.id)
    if task.task_type == TaskType.TIME_DETERMINISTIC:
        return (
            float(task.period) if task.period is not None else None,
            "task.period" if task.period is not None else "not_available",
        )

    process = task.arrival_process
    if process is not None:
        params = dict(process.params)
        if process.type == ArrivalProcessType.ONE_SHOT:
            return None, "one_shot"
        if process.type == ArrivalProcessType.FIXED:
            if params.get("interval") is not None:
                return _resolve_positive_interval(params.get("interval")), "arrival_process.params.interval"
            source = "task.min_inter_arrival" if task.min_inter_arrival is not None else "task.period"
            return _resolve_positive_interval(task.min_inter_arrival, fallback=task.period), source
        if process.type == ArrivalProcessType.UNIFORM:
            if params.get("min_interval") is not None:
                return _resolve_positive_interval(params.get("min_interval")), "arrival_process.params.min_interval"
            source = "task.min_inter_arrival" if task.min_inter_arrival is not None else "task.period"
            return _resolve_positive_interval(task.min_inter_arrival, fallback=task.period), source
        if process.type == ArrivalProcessType.POISSON:
            if arrival_analysis_mode == "conservative_envelope" and override is not None:
                return float(override), f"planning.params.arrival_envelope_min_intervals.{task.id}"
            return None, (
                "planning.params.arrival_envelope_min_intervals.available_not_used"
                if override is not None
                else "not_available_in_sample_path"
            )
        if process.type == ArrivalProcessType.CUSTOM:
            generator_name = _arrival_generator_name(task)
            builtin_interval, builtin_source = resolve_generator_min_interval(generator_name, params)
            if builtin_interval is not None and builtin_source is not None:
                return builtin_interval, builtin_source
            if arrival_analysis_mode == "conservative_envelope" and override is not None:
                return float(override), f"planning.params.arrival_envelope_min_intervals.{task.id}"
            return None, (
                "planning.params.arrival_envelope_min_intervals.available_not_used"
                if override is not None
                else f"custom_generator:{generator_name}(no_builtin_lower_bound)"
            )

    if task.task_type == TaskType.DYNAMIC_RT:
        arrival_model = _arrival_generator_name(task)
        if arrival_model in {"fixed_interval", "uniform_interval"}:
            source = "task.min_inter_arrival" if task.min_inter_arrival is not None else "task.period"
            return _resolve_positive_interval(task.min_inter_arrival, fallback=task.period), source

    if arrival_analysis_mode == "conservative_envelope" and override is not None:
        return float(override), f"planning.params.arrival_envelope_min_intervals.{task.id}"
    return None, "not_available"


def _build_arrival_assumption_trace(
    spec: ModelSpec,
    *,
    included_task_ids: set[str],
    arrival_analysis_mode: str,
    conservative_min_intervals: dict[str, float],
) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    any_seeded = False
    for task in spec.tasks:
        if task.id not in included_task_ids:
            continue
        generator = _arrival_generator_name(task)
        seed_source = _arrival_trace_seed_source(task, arrival_analysis_mode=arrival_analysis_mode)
        resolved_min_interval, envelope_source = _arrival_min_interval_and_source(
            task,
            arrival_analysis_mode=arrival_analysis_mode,
            conservative_min_intervals=conservative_min_intervals,
        )
        any_seeded = any_seeded or seed_source == "sim.seed"
        tasks.append(
            {
                "task_id": task.id,
                "task_type": task.task_type.value,
                "arrival_mode": _task_arrival_mode(task),
                "generator": generator,
                "seed_source": seed_source,
                "resolved_min_interval": resolved_min_interval,
                "envelope_source": envelope_source,
            }
        )
    return {
        "arrival_analysis_mode": arrival_analysis_mode,
        "seed_source": (
            "sim.seed"
            if any_seeded and arrival_analysis_mode == "sample_path"
            else (
                "not_used(conservative_envelope)"
                if arrival_analysis_mode == "conservative_envelope"
                else "not_required"
            )
        ),
        "seed_value": int(spec.sim.seed) if any_seeded and arrival_analysis_mode == "sample_path" else None,
        "task_count": len(tasks),
        "tasks": tasks,
    }


def _next_release_time(
    ctx: _PlanningArrivalContext,
    task: TaskGraphSpec,
    release_idx: int,
    current_release: float,
) -> float | None:
    process = task.arrival_process
    process_type = process.type.value if process is not None else None
    params = dict(process.params) if process is not None else {}
    if process is not None and process.max_releases is not None and release_idx >= process.max_releases:
        return None

    if ctx.mode == "conservative_envelope":
        interval = _conservative_interval(ctx, task, process_type=process_type, params=params)
        if interval is None:
            return None
        return current_release + interval
    if process is not None:
        if process_type == "one_shot":
            return None
        if process_type == "fixed":
            interval = _resolve_positive_interval(
                params.get("interval"),
                fallback=task.min_inter_arrival if task.min_inter_arrival is not None else task.period,
            )
            if interval is None:
                raise ValueError("arrival_process type=fixed requires interval")
            return current_release + interval
        if process_type == "uniform":
            lower = _resolve_positive_interval(
                params.get("min_interval"),
                fallback=task.min_inter_arrival if task.min_inter_arrival is not None else task.period,
            )
            upper = _resolve_positive_interval(
                params.get("max_interval"),
                fallback=task.max_inter_arrival,
            )
            if lower is None or upper is None:
                raise ValueError("arrival_process type=uniform requires min_interval and max_interval")
            if upper < lower - 1e-12:
                raise ValueError("arrival_process uniform max_interval must be >= min_interval")
            return current_release + ctx.rng.uniform(lower, upper)
        if process_type == "poisson":
            rate = _resolve_positive_interval(params.get("rate"))
            if rate is None:
                raise ValueError("arrival_process type=poisson requires rate")
            return current_release + ctx.rng.expovariate(rate)
        if process_type == "custom":
            generator_name = params.get("generator")
            if not isinstance(generator_name, str) or not generator_name.strip():
                raise ValueError("arrival_process type=custom requires params.generator")
            generator = ctx.generators.setdefault(generator_name.strip().lower(), create_arrival_generator(generator_name))
            interval = generator.next_interval(
                task=task,
                now=current_release,
                current_release=current_release,
                release_index=release_idx,
                params=dict(params),
                rng=ctx.rng,
            )
            if not isinstance(interval, (int, float)):
                raise ValueError("custom arrival generator must return numeric interval")
            resolved_interval = float(interval)
            if resolved_interval <= 0:
                raise ValueError("custom arrival generator interval must be > 0")
            return current_release + resolved_interval
        raise ValueError(f"unsupported arrival_process type: {process_type}")

    if task.task_type == TaskType.TIME_DETERMINISTIC:
        if task.period is None:
            return None
        return _release_base_time(task) + float(task.period) * release_idx
    if task.task_type == TaskType.DYNAMIC_RT:
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
            interval = ctx.rng.uniform(interval, upper_bound)
        elif arrival_model != "fixed_interval":
            raise ValueError(f"unsupported dynamic arrival model: {arrival_model}")
        if interval <= 0:
            raise ValueError("computed dynamic release interval must be > 0")
        return current_release + float(interval)
    return None


def _expanded_release_schedule(spec: ModelSpec, horizon: float) -> dict[str, list[tuple[int, float]]]:
    ctx = _PlanningArrivalContext(
        spec.sim.seed,
        mode=_arrival_analysis_mode(spec),
        conservative_min_intervals=_conservative_min_interval_map(spec),
    )
    release_times: dict[str, list[tuple[int, float]]] = {task.id: [] for task in spec.tasks}
    heap: list[tuple[float, int, str]] = []
    tasks_by_id = {task.id: task for task in spec.tasks}
    for task in spec.tasks:
        base_release = _release_base_time(task)
        if base_release <= horizon + 1e-12:
            heapq.heappush(heap, (base_release, 0, task.id))
    while heap:
        release_time, release_idx, task_id = heapq.heappop(heap)
        if release_time > horizon + 1e-12:
            break
        release_times[task_id].append((release_idx, float(release_time)))
        task = tasks_by_id[task_id]
        next_idx = release_idx + 1
        next_release = _next_release_time(ctx, task, next_idx, float(release_time))
        if next_release is not None and next_release <= horizon + 1e-12:
            heapq.heappush(heap, (float(next_release), next_idx, task_id))
    return release_times


@dataclass(slots=True)
class NormalizedCore:
    core_id: str
    processor_type_id: str
    processor_speed_factor: float
    core_speed_factor: float
    effective_speed_factor: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "core_id": self.core_id,
            "processor_type_id": self.processor_type_id,
            "processor_speed_factor": self.processor_speed_factor,
            "core_speed_factor": self.core_speed_factor,
            "effective_speed_factor": self.effective_speed_factor,
        }


@dataclass(slots=True)
class NormalizedSegment:
    task_id: str
    subtask_id: str
    segment_id: str
    key: str
    task_type: str
    wcet: float
    release_index: int | None
    release_time: float
    period: float | None
    relative_deadline: float | None
    absolute_deadline: float | None
    arrival_mode: str
    phase_offset: float | None
    mapping_hint: str | None
    required_resources: list[str] = field(default_factory=list)
    predecessor_keys: list[str] = field(default_factory=list)
    preemptible: bool = True
    release_offsets: list[float] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "subtask_id": self.subtask_id,
            "segment_id": self.segment_id,
            "key": self.key,
            "task_type": self.task_type,
            "wcet": self.wcet,
            "release_index": self.release_index,
            "release_time": self.release_time,
            "period": self.period,
            "relative_deadline": self.relative_deadline,
            "absolute_deadline": self.absolute_deadline,
            "arrival_mode": self.arrival_mode,
            "phase_offset": self.phase_offset,
            "mapping_hint": self.mapping_hint,
            "required_resources": list(self.required_resources),
            "predecessor_keys": list(self.predecessor_keys),
            "preemptible": self.preemptible,
            "release_offsets": list(self.release_offsets),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class NormalizedExecutionModel:
    task_scope: str
    include_non_rt: bool
    horizon: float | None
    cores: list[NormalizedCore]
    segments: list[NormalizedSegment]
    resource_bindings: dict[str, dict[str, str]]
    scheduler_context: dict[str, Any]
    coverage_summary: dict[str, Any]
    assumptions: list[dict[str, Any]] = field(default_factory=list)
    unsupported_dimensions: list[dict[str, Any]] = field(default_factory=list)
    arrival_assumption_trace: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_model_spec(
        cls,
        spec: ModelSpec,
        *,
        task_scope: str | None = None,
        include_non_rt: bool = False,
        horizon: float | None = None,
    ) -> "NormalizedExecutionModel":
        resolved_scope = normalize_task_scope(task_scope, include_non_rt=include_non_rt)
        processor_speed = {
            processor.id: float(processor.speed_factor)
            for processor in spec.platform.processor_types
        }
        cores = [
            NormalizedCore(
                core_id=core.id,
                processor_type_id=core.type_id,
                processor_speed_factor=processor_speed[core.type_id],
                core_speed_factor=float(core.speed_factor),
                effective_speed_factor=float(core.speed_factor) * processor_speed[core.type_id],
            )
            for core in spec.platform.cores
        ]

        resource_bindings = {
            resource.id: {
                "bound_core_id": resource.bound_core_id,
                "protocol": resource.protocol,
            }
            for resource in spec.resources
        }
        core_ids = [core.core_id for core in cores]
        core_speed_by_id = {core.core_id: core.effective_speed_factor for core in cores}
        effective_speeds = sorted({round(core.effective_speed_factor, 12) for core in cores})
        scheduler_params = dict(spec.scheduler.params)
        overhead_params = scheduler_params.get("overhead", {})
        if not isinstance(overhead_params, dict):
            overhead_params = {}
        etm_params = scheduler_params.get("etm_params", {})
        if not isinstance(etm_params, dict):
            etm_params = {}
        etm_name = str(scheduler_params.get("etm", "constant") or "constant")
        arrival_analysis_mode = _arrival_analysis_mode(spec)
        conservative_min_intervals = _conservative_min_interval_map(spec)
        etm = create_etm(etm_name, etm_params)

        segments: list[NormalizedSegment] = []
        included_task_ids: set[str] = set()
        skipped_dynamic_rt = 0
        skipped_non_rt = 0
        resource_segment_count = 0
        release_offset_segment_count = 0
        non_preemptible_segment_count = 0
        stochastic_arrival_task_count = 0
        phase_offset_task_count = 0
        expanded_release_count = 0
        analysis_horizon = float(horizon) if horizon is not None else float(spec.sim.duration)
        release_schedule = _expanded_release_schedule(spec, analysis_horizon)

        for task in spec.tasks:
            if not _task_in_scope(task.task_type, resolved_scope):
                if task.task_type == TaskType.DYNAMIC_RT:
                    skipped_dynamic_rt += 1
                elif task.task_type == TaskType.NON_RT:
                    skipped_non_rt += 1
                continue

            included_task_ids.add(task.id)
            if task.phase_offset not in (None, 0.0):
                phase_offset_task_count += 1
            arrival_mode = _task_arrival_mode(task)
            if arrival_mode in {
                ArrivalProcessType.UNIFORM.value,
                ArrivalProcessType.POISSON.value,
                ArrivalProcessType.CUSTOM.value,
                "uniform_interval",
            }:
                stochastic_arrival_task_count += 1

            relative_deadline = float(task.deadline) if task.deadline is not None else None
            task_mapping = task.task_mapping_hint
            task_releases = release_schedule.get(task.id, [])
            expanded_release_count += len(task_releases)

            for release_idx, task_release_time in task_releases:
                release_marker = release_idx if len(task_releases) > 1 else None
                absolute_deadline = (
                    task_release_time + relative_deadline if relative_deadline is not None else None
                )
                subtask_segment_keys: dict[str, list[str]] = {}

                for subtask in task.subtasks:
                    ordered_segments = sorted(subtask.segments, key=lambda item: item.index)
                    subtask_mapping = subtask.subtask_mapping_hint or task_mapping
                    previous_segment_key: str | None = None
                    subtask_keys: list[str] = []

                    for segment in ordered_segments:
                        mapping_hint = segment.mapping_hint or subtask_mapping
                        release_offsets = [float(value) for value in (segment.release_offsets or [])]
                        effective_release_time = float(task_release_time)
                        deterministic_offset_index: int | None = None
                        if release_offsets:
                            deterministic_offset_index = release_idx % len(release_offsets)
                            effective_release_time += release_offsets[deterministic_offset_index]

                        eligible_core_ids = [mapping_hint] if mapping_hint else list(core_ids)
                        execution_cost_by_core = {
                            core_id: float(
                                etm.estimate(
                                    float(segment.wcet),
                                    float(core_speed_by_id[core_id]),
                                    effective_release_time,
                                    task_id=task.id,
                                    subtask_id=subtask.id,
                                    segment_id=segment.id,
                                    core_id=core_id,
                                )
                            )
                            for core_id in eligible_core_ids
                        }
                        default_execution_cost = (
                            min(execution_cost_by_core.values())
                            if execution_cost_by_core
                            else float(segment.wcet)
                        )
                        segment_key = (f"{task.id}@{release_idx}:{subtask.id}:{segment.id}" if release_marker is not None else f"{task.id}:{subtask.id}:{segment.id}")
                        normalized_segment = NormalizedSegment(
                            task_id=task.id,
                            subtask_id=subtask.id,
                            segment_id=segment.id,
                            key=segment_key,
                            task_type=task.task_type.value,
                            wcet=float(segment.wcet),
                            release_index=release_marker,
                            release_time=effective_release_time,
                            period=float(task.period) if task.period is not None else None,
                            relative_deadline=relative_deadline,
                            absolute_deadline=absolute_deadline,
                            arrival_mode=arrival_mode,
                            phase_offset=float(task.phase_offset) if task.phase_offset is not None else None,
                            mapping_hint=mapping_hint,
                            required_resources=list(segment.required_resources),
                            predecessor_keys=[previous_segment_key] if previous_segment_key else [],
                            preemptible=bool(segment.preemptible),
                            release_offsets=release_offsets,
                            metadata={
                                "segment_index": int(segment.index),
                                "task_name": task.name,
                                "subtask_successor_count": len(subtask.successors),
                                "eligible_core_ids": list(eligible_core_ids),
                                "execution_cost_by_core": {
                                    core_id: round(cost, 12)
                                    for core_id, cost in sorted(execution_cost_by_core.items())
                                },
                                "default_execution_cost": round(default_execution_cost, 12),
                                "raw_wcet": float(segment.wcet),
                                "effective_speed_by_core": {
                                    core_id: float(core_speed_by_id[core_id])
                                    for core_id in eligible_core_ids
                                },
                                "etm": etm_name,
                                "release_index": int(release_idx),
                                "task_release_time": float(task_release_time),
                                "analysis_release_time": float(effective_release_time),
                                "deterministic_offset_index": deterministic_offset_index,
                            },
                        )
                        if normalized_segment.required_resources:
                            resource_segment_count += 1
                        if normalized_segment.release_offsets:
                            release_offset_segment_count += 1
                        if not normalized_segment.preemptible:
                            non_preemptible_segment_count += 1
                        segments.append(normalized_segment)
                        subtask_keys.append(segment_key)
                        previous_segment_key = segment_key
                    subtask_segment_keys[subtask.id] = subtask_keys

                by_key = {
                    segment.key: segment
                    for segment in segments
                    if segment.task_id == task.id and (segment.release_index or 0) == (release_marker if release_marker is not None else 0)
                }
                for subtask in task.subtasks:
                    current_keys = subtask_segment_keys.get(subtask.id, [])
                    if not current_keys:
                        continue
                    first_segment = by_key[current_keys[0]]
                    for predecessor_subtask in subtask.predecessors:
                        predecessor_keys = subtask_segment_keys.get(predecessor_subtask, [])
                        if not predecessor_keys:
                            continue
                        predecessor_key = predecessor_keys[-1]
                        if predecessor_key not in first_segment.predecessor_keys:
                            first_segment.predecessor_keys.append(predecessor_key)

        assumptions = [
            {
                "id": "release_expansion_within_horizon",
                "message": "Offline planning/WCRT expand task releases within the selected horizon (defaults to sim.duration), instead of collapsing tasks to one representative release.",
                "horizon": analysis_horizon,
                "expanded_release_count": expanded_release_count,
            },
            {
                "id": "stochastic_arrival_expansion_mode",
                "message": (
                    "Uniform/Poisson/custom arrivals are expanded as a deterministic sample path driven by sim.seed and the shared release queue order."
                    if arrival_analysis_mode == "sample_path"
                    else "Uniform/Poisson/custom arrivals are expanded using conservative minimum-interval envelopes when available."
                ),
                "arrival_analysis_mode": arrival_analysis_mode,
                "conservative_envelope_override_count": len(conservative_min_intervals),
            },
            {
                "id": "runtime_static_window_materialization",
                "message": "Runtime consumes planning artifacts by materializing runtime_static_windows into scheduler.params.static_windows.",
            },
        ]

        unsupported_dimensions: list[dict[str, Any]] = []
        if resource_segment_count > 0:
            unsupported_dimensions.append(
                {
                    "id": "resource_blocking_not_in_static_plan",
                    "message": "Static planning feasibility does not expand runtime resource contention directly; blocking is modeled analytically in WCRT.",
                    "segment_count": resource_segment_count,
                }
            )
        if any(float(overhead_params.get(key, 0.0) or 0.0) > 0.0 for key in ("context_switch", "migration", "schedule")):
            unsupported_dimensions.append(
                {
                    "id": "runtime_overheads_not_in_static_plan",
                    "message": "Static planning feasibility does not fully expand runtime scheduling/context/migration overheads; WCRT models these costs analytically.",
                    "overhead": {
                        key: float(overhead_params.get(key, 0.0) or 0.0)
                        for key in ("context_switch", "migration", "schedule")
                    },
                }
            )
        if non_preemptible_segment_count > 0:
            unsupported_dimensions.append(
                {
                    "id": "segment_preemptibility_not_modeled",
                    "message": "Segment-level preemptible flags are enforced at runtime, but offline planning/WCRT do not derive separate bounds from them.",
                    "segment_count": non_preemptible_segment_count,
                }
            )

        coverage_summary = {
            "source": "model_spec",
            "task_scope": resolved_scope,
            "include_non_rt": bool(include_non_rt),
            "horizon": horizon,
            "analysis_horizon": analysis_horizon,
            "arrival_analysis_mode": arrival_analysis_mode,
            "conservative_envelope_override_count": len(conservative_min_intervals),
            "total_tasks": len(spec.tasks),
            "included_task_count": len(included_task_ids),
            "included_segment_count": len(segments),
            "expanded_release_count": expanded_release_count,
            "skipped_dynamic_rt_tasks": skipped_dynamic_rt,
            "skipped_non_rt_tasks": skipped_non_rt,
            "resource_segment_count": resource_segment_count,
            "release_offset_segment_count": release_offset_segment_count,
            "non_preemptible_segment_count": non_preemptible_segment_count,
            "stochastic_arrival_task_count": stochastic_arrival_task_count,
            "phase_offset_task_count": phase_offset_task_count,
            "unsupported_dimension_count": len(unsupported_dimensions),
            "effective_core_speed_count": len(effective_speeds),
            "etm_name": etm_name,
        }

        arrival_assumption_trace = _build_arrival_assumption_trace(
            spec,
            included_task_ids=included_task_ids,
            arrival_analysis_mode=arrival_analysis_mode,
            conservative_min_intervals=conservative_min_intervals,
        )

        scheduler_context = {
            "scheduler_name": spec.scheduler.name,
            "resource_acquire_policy": scheduler_params.get("resource_acquire_policy", "legacy_sequential"),
            "etm": str(scheduler_params.get("etm", "constant") or "constant"),
            "etm_params": dict(etm_params),
            "overhead_model": str(scheduler_params.get("overhead_model", "default") or "default"),
            "overhead": {
                key: float(overhead_params.get(key, 0.0) or 0.0)
                for key in ("context_switch", "migration", "schedule")
            },
        }
        return cls(
            task_scope=resolved_scope,
            include_non_rt=bool(include_non_rt),
            horizon=analysis_horizon,
            cores=sorted(cores, key=lambda item: item.core_id),
            segments=sorted(segments, key=lambda item: item.key),
            resource_bindings=resource_bindings,
            scheduler_context=scheduler_context,
            coverage_summary=coverage_summary,
            assumptions=assumptions,
            unsupported_dimensions=unsupported_dimensions,
            arrival_assumption_trace=arrival_assumption_trace,
        )

    def fingerprint_payload(self) -> dict[str, Any]:
        return {
            "task_scope": self.task_scope,
            "include_non_rt": self.include_non_rt,
            "horizon": self.horizon,
            "scheduler_context": dict(self.scheduler_context),
            "resource_bindings": {
                resource_id: dict(binding)
                for resource_id, binding in sorted(self.resource_bindings.items())
            },
            "cores": [core.to_dict() for core in self.cores],
            "segments": [segment.to_dict() for segment in self.segments],
        }

    def semantic_fingerprint(self) -> str:
        canonical_json = _json_dumps(self.fingerprint_payload())
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    def to_planning_problem(self):
        from .types import PlanningProblem, PlanningSegment

        segments = [
            PlanningSegment(
                task_id=segment.task_id,
                subtask_id=segment.subtask_id,
                segment_id=segment.segment_id,
                wcet=segment.wcet,
                release_index=segment.release_index,
                release_time=segment.release_time,
                period=segment.period,
                relative_deadline=segment.relative_deadline,
                absolute_deadline=segment.absolute_deadline,
                mapping_hint=segment.mapping_hint,
                predecessors=list(segment.predecessor_keys),
                metadata={
                    **dict(segment.metadata),
                    "task_type": segment.task_type,
                    "arrival_mode": segment.arrival_mode,
                    "preemptible": segment.preemptible,
                    "required_resources": list(segment.required_resources),
                    "required_resource_count": len(segment.required_resources),
                    "release_offsets": list(segment.release_offsets),
                    "release_offset_count": len(segment.release_offsets),
                    "raw_wcet": segment.wcet,
                    "base_segment_key": f"{segment.task_id}:{segment.subtask_id}:{segment.segment_id}",
                },
            )
            for segment in self.segments
        ]
        return PlanningProblem(
            core_ids=[core.core_id for core in self.cores],
            segments=segments,
            horizon=float(self.coverage_summary.get("analysis_horizon", self.horizon or 0.0)) if (self.coverage_summary.get("analysis_horizon") is not None or self.horizon is not None) else None,
            metadata={
                **dict(self.coverage_summary),
                "task_scope": self.task_scope,
                "include_non_rt": self.include_non_rt,
                "horizon": self.horizon,
                "semantic_fingerprint": self.semantic_fingerprint(),
                "scheduler_context": dict(self.scheduler_context),
                "resource_bindings": {
                    resource_id: dict(binding)
                    for resource_id, binding in sorted(self.resource_bindings.items())
                },
                "assumptions": [dict(item) for item in self.assumptions],
                "unsupported_dimensions": [dict(item) for item in self.unsupported_dimensions],
                "arrival_assumption_trace": dict(self.arrival_assumption_trace),
            },
        )


def build_normalized_execution_model(
    spec: ModelSpec,
    *,
    task_scope: str | None = None,
    include_non_rt: bool = False,
    horizon: float | None = None,
) -> NormalizedExecutionModel:
    return NormalizedExecutionModel.from_model_spec(
        spec,
        task_scope=task_scope,
        include_non_rt=include_non_rt,
        horizon=horizon,
    )
