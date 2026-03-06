"""Analytical WCRT/RTA based on static schedule tables."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from math import ceil
from typing import Any

from .types import PlanningEvidence, PlanningProblem, ScheduleTable, WCRTItem, WCRTReport, execution_cost_for_core


EPSILON = 1e-12


@dataclass(slots=True)
class _TaskProfile:
    task_id: str
    logical_task_id: str = ""
    release_index: int | None = None
    task_type: str = "unknown"
    wcet: float = 0.0
    period: float | None = None
    deadline: float | None = None
    absolute_deadline: float | None = None
    release_time: float = float("inf")
    windows_start: float | None = None
    windows_end: float | None = None
    cores: set[str] = field(default_factory=set)
    successors: set[str] = field(default_factory=set)
    predecessors: set[str] = field(default_factory=set)
    segment_count: int = 0
    window_count: int = 0
    migration_transition_count: int = 0
    required_resources: set[str] = field(default_factory=set)
    critical_section_by_resource: dict[str, float] = field(default_factory=dict)

    def priority_key(self) -> tuple[float, float, float, str]:
        absolute_deadline = self.absolute_deadline
        if absolute_deadline is None and self.deadline is not None:
            absolute_deadline = self.release_time + self.deadline
        deadline = self.deadline if self.deadline is not None else float("inf")
        period = self.period if self.period is not None else float("inf")
        return (absolute_deadline if absolute_deadline is not None else float("inf"), deadline, period, self.task_id)

    def response_window_end(self) -> float:
        if self.windows_end is not None:
            return self.windows_end
        return self.release_time + self.wcet

    def task_window_start(self) -> float:
        if self.windows_start is not None:
            return min(self.release_time, self.windows_start)
        return self.release_time

    def dispatch_count(self) -> int:
        return self.window_count if self.window_count > 0 else max(self.segment_count, 1)


def _profile_key(task_id: str, release_index: int | None) -> str:
    if release_index is None:
        return task_id
    return f"{task_id}@{release_index}"


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, str) and item.strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if isinstance(item, str) and item.strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _scheduler_context(problem: PlanningProblem) -> dict[str, Any]:
    payload = problem.metadata.get("scheduler_context")
    return dict(payload) if isinstance(payload, dict) else {}


def _resource_bindings(problem: PlanningProblem) -> dict[str, dict[str, Any]]:
    payload = problem.metadata.get("resource_bindings")
    if not isinstance(payload, dict):
        return {}
    return {
        str(resource_id): dict(binding)
        for resource_id, binding in payload.items()
        if isinstance(resource_id, str) and isinstance(binding, dict)
    }


def _scheduler_overheads(problem: PlanningProblem) -> dict[str, float]:
    scheduler_context = _scheduler_context(problem)
    payload = scheduler_context.get("overhead")
    if not isinstance(payload, dict):
        payload = {}
    return {
        "context_switch": float(payload.get("context_switch", 0.0) or 0.0),
        "migration": float(payload.get("migration", 0.0) or 0.0),
        "schedule": float(payload.get("schedule", 0.0) or 0.0),
    }


def _build_profiles(problem: PlanningProblem, schedule_table: ScheduleTable) -> dict[str, _TaskProfile]:
    profiles: dict[str, _TaskProfile] = {}
    windows_by_task: dict[str, list] = defaultdict(list)
    window_core_by_segment = {window.segment_key: str(window.core_id) for window in schedule_table.windows}

    for segment in problem.segments:
        profile_key = _profile_key(segment.task_id, segment.release_index)
        profile = profiles.setdefault(
            profile_key,
            _TaskProfile(
                task_id=profile_key,
                logical_task_id=segment.task_id,
                release_index=segment.release_index,
            ),
        )
        task_type = segment.metadata.get("task_type")
        if isinstance(task_type, str) and task_type.strip():
            profile.task_type = task_type.strip().lower()
        assigned_core_id = window_core_by_segment.get(segment.key, segment.mapping_hint)
        segment_execution_cost = execution_cost_for_core(segment, assigned_core_id)
        profile.segment_count += 1
        profile.wcet += float(segment_execution_cost)
        profile.release_time = min(profile.release_time, float(segment.release_time))
        if profile.period is None or (
            segment.period is not None and float(segment.period) < profile.period
        ):
            profile.period = float(segment.period) if segment.period is not None else profile.period
        if profile.deadline is None or (
            segment.relative_deadline is not None and float(segment.relative_deadline) < profile.deadline
        ):
            profile.deadline = (
                float(segment.relative_deadline)
                if segment.relative_deadline is not None
                else profile.deadline
            )
        if profile.absolute_deadline is None or (
            segment.absolute_deadline is not None and float(segment.absolute_deadline) < profile.absolute_deadline
        ):
            profile.absolute_deadline = (
                float(segment.absolute_deadline)
                if segment.absolute_deadline is not None
                else profile.absolute_deadline
            )
        if segment.mapping_hint:
            profile.cores.add(segment.mapping_hint)
        required_resources = _as_string_list(segment.metadata.get("required_resources"))
        profile.required_resources.update(required_resources)
        for resource_id in required_resources:
            previous = profile.critical_section_by_resource.get(resource_id, 0.0)
            profile.critical_section_by_resource[resource_id] = max(previous, segment_execution_cost)

    segment_to_task = {segment.key: _profile_key(segment.task_id, segment.release_index) for segment in problem.segments}
    for segment in problem.segments:
        current_task = _profile_key(segment.task_id, segment.release_index)
        profile = profiles[current_task]
        for predecessor in segment.predecessors:
            predecessor_task = segment_to_task.get(predecessor)
            if predecessor_task is None or predecessor_task == current_task:
                continue
            profile.predecessors.add(predecessor_task)
            profiles.setdefault(predecessor_task, _TaskProfile(task_id=predecessor_task)).successors.add(
                current_task
            )

    for window in schedule_table.windows:
        profile_key = _profile_key(window.task_id, window.release_index)
        profile = profiles.setdefault(
            profile_key,
            _TaskProfile(
                task_id=profile_key,
                logical_task_id=window.task_id,
                release_index=window.release_index,
            ),
        )
        profile.cores.add(window.core_id)
        profile.windows_start = (
            float(window.start_time)
            if profile.windows_start is None
            else min(profile.windows_start, float(window.start_time))
        )
        profile.windows_end = (
            float(window.end_time)
            if profile.windows_end is None
            else max(profile.windows_end, float(window.end_time))
        )
        profile.release_time = min(profile.release_time, float(window.release_time))
        windows_by_task[profile_key].append(window)

    for task_id, windows in windows_by_task.items():
        profile = profiles[task_id]
        ordered_windows = sorted(
            windows,
            key=lambda item: (float(item.start_time), float(item.end_time), item.segment_key),
        )
        profile.window_count = len(ordered_windows)
        previous_core_id: str | None = None
        for window in ordered_windows:
            current_core_id = str(window.core_id)
            if previous_core_id is not None and current_core_id != previous_core_id:
                profile.migration_transition_count += 1
            previous_core_id = current_core_id

    for profile in profiles.values():
        if profile.release_time == float("inf"):
            profile.release_time = 0.0
        if profile.period is None:
            profile.period = profile.deadline if profile.deadline is not None else None
        if profile.deadline is None and profile.period is not None:
            profile.deadline = profile.period
    return profiles


def _reachable(task_id: str, *, edges: dict[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    stack = [task_id]
    while stack:
        current = stack.pop()
        for nxt in edges.get(current, set()):
            if nxt in seen:
                continue
            seen.add(nxt)
            stack.append(nxt)
    return seen


def _build_independent_map(profiles: dict[str, _TaskProfile]) -> dict[str, set[str]]:
    succ_edges = {task_id: set(profile.successors) for task_id, profile in profiles.items()}
    pred_edges = {task_id: set(profile.predecessors) for task_id, profile in profiles.items()}
    descendants = {task_id: _reachable(task_id, edges=succ_edges) for task_id in profiles}
    ancestors = {task_id: _reachable(task_id, edges=pred_edges) for task_id in profiles}

    independent: dict[str, set[str]] = {}
    for task_id in profiles:
        dependent = descendants[task_id] | ancestors[task_id] | {task_id}
        independent[task_id] = {other for other in profiles if other not in dependent}
    return independent


def _sync_interference(
    task_id: str,
    *,
    profile: _TaskProfile,
    windows_by_task: dict[str, list],
    profiles: dict[str, _TaskProfile],
) -> tuple[float, dict[str, float]]:
    interval_start = profile.task_window_start()
    interval_end = profile.response_window_end()
    if interval_end <= interval_start + EPSILON:
        return 0.0, {}
    interference = 0.0
    by_task: dict[str, float] = defaultdict(float)

    for other_task, windows in windows_by_task.items():
        if other_task == task_id:
            continue
        other_profile = profiles.get(other_task)
        if other_profile is None or other_profile.task_type != "time_deterministic":
            continue
        for window in windows:
            if profile.cores and window.core_id not in profile.cores:
                continue
            overlap_start = max(interval_start, float(window.start_time))
            overlap_end = min(interval_end, float(window.end_time))
            if overlap_end > overlap_start + EPSILON:
                delta = overlap_end - overlap_start
                interference += delta
                by_task[other_task] += delta
    return interference, dict(by_task)


def _task_dispatch_overhead(profile: _TaskProfile, *, overheads: dict[str, float]) -> float:
    per_dispatch = overheads["context_switch"] + overheads["schedule"]
    return profile.dispatch_count() * per_dispatch


def _task_migration_overhead(profile: _TaskProfile, *, overheads: dict[str, float]) -> float:
    return profile.migration_transition_count * overheads["migration"]


def _task_job_cost(profile: _TaskProfile, *, overheads: dict[str, float]) -> float:
    return profile.wcet + _task_dispatch_overhead(profile, overheads=overheads) + _task_migration_overhead(
        profile,
        overheads=overheads,
    )


def _resource_blocking(
    task_id: str,
    *,
    profile: _TaskProfile,
    profiles: dict[str, _TaskProfile],
    resource_bindings: dict[str, dict[str, Any]],
    overheads: dict[str, float],
) -> tuple[float, dict[str, float]]:
    if not profile.required_resources:
        return 0.0, {}
    current_key = profile.priority_key()
    max_blocking = 0.0
    blocking_sources: dict[str, float] = {}
    dispatch_cost = overheads["context_switch"] + overheads["schedule"]

    for other_task_id, other_profile in profiles.items():
        if other_task_id == task_id:
            continue
        if other_profile.priority_key() <= current_key:
            continue
        shared_resources = sorted(profile.required_resources & other_profile.required_resources)
        if not shared_resources:
            continue
        for resource_id in shared_resources:
            critical_section = other_profile.critical_section_by_resource.get(resource_id, 0.0)
            if critical_section <= EPSILON:
                continue
            candidate = critical_section + dispatch_cost
            if candidate <= max_blocking + EPSILON:
                continue
            binding = resource_bindings.get(resource_id, {})
            protocol = binding.get("protocol") if isinstance(binding, dict) else None
            source_key = f"{other_task_id}:{resource_id}:{protocol or 'unknown'}"
            max_blocking = candidate
            blocking_sources = {source_key: round(candidate, 9)}
    return max_blocking, blocking_sources


def _high_priority_independent_tasks(
    task_id: str,
    *,
    profiles: dict[str, _TaskProfile],
    independent_map: dict[str, set[str]],
) -> list[_TaskProfile]:
    current = profiles[task_id]
    current_key = current.priority_key()
    candidates: list[_TaskProfile] = []
    for other in independent_map.get(task_id, set()):
        other_profile = profiles[other]
        if other_profile.task_type == "time_deterministic":
            continue
        if current.cores and other_profile.cores and current.cores.isdisjoint(other_profile.cores):
            continue
        if other_profile.priority_key() < current_key:
            candidates.append(other_profile)
    candidates.sort(key=lambda item: item.priority_key())
    return candidates


def _filtered_unsupported_dimensions(problem: PlanningProblem) -> list[dict[str, Any]]:
    payload = problem.metadata.get("unsupported_dimensions")
    if not isinstance(payload, list):
        return []
    filtered: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        if item_id in {"resource_blocking_not_in_static_plan", "runtime_overheads_not_in_static_plan"}:
            continue
        filtered.append(dict(item))
    return filtered


def analyze_wcrt(
    problem: PlanningProblem,
    schedule_table: ScheduleTable,
    *,
    max_iterations: int = 64,
    epsilon: float = 1e-9,
) -> WCRTReport:
    """Compute per-task WCRT with fixed-point RTA iterations."""

    profiles = _build_profiles(problem, schedule_table)
    independent_map = _build_independent_map(profiles)
    windows_by_task = defaultdict(list)
    for window in schedule_table.windows:
        profile_key = _profile_key(window.task_id, window.release_index)
        windows_by_task[profile_key].append(window)

    resource_bindings = _resource_bindings(problem)
    overheads = _scheduler_overheads(problem)
    scheduler_context = _scheduler_context(problem)
    effective_core_speed_count = int(problem.metadata.get("effective_core_speed_count", 1) or 1)
    etm_name = str(scheduler_context.get("etm", "constant") or "constant")
    has_resource_blocking_model = any(profile.required_resources for profile in profiles.values())
    has_overhead_model = any(value > EPSILON for value in overheads.values())
    has_heterogeneous_speed_model = effective_core_speed_count > 1
    has_etm_scaling_model = etm_name not in {"", "default", "constant"}

    items: list[WCRTItem] = []
    evidence: list[PlanningEvidence] = []
    all_schedulable = True

    for task_id in sorted(profiles):
        profile = profiles[task_id]
        sync_interference, sync_sources = _sync_interference(
            task_id,
            profile=profile,
            windows_by_task=windows_by_task,
            profiles=profiles,
        )
        blocking_bound, blocking_sources = _resource_blocking(
            task_id,
            profile=profile,
            profiles=profiles,
            resource_bindings=resource_bindings,
            overheads=overheads,
        )
        hp_independent = _high_priority_independent_tasks(
            task_id,
            profiles=profiles,
            independent_map=independent_map,
        )
        hp_names = [item.task_id for item in hp_independent]
        hp_job_costs = {
            hp_task.task_id: round(_task_job_cost(hp_task, overheads=overheads), 9)
            for hp_task in hp_independent
        }

        dispatch_overhead = _task_dispatch_overhead(profile, overheads=overheads)
        migration_overhead = _task_migration_overhead(profile, overheads=overheads)
        own_execution_cost = profile.wcet + dispatch_overhead + migration_overhead
        base = own_execution_cost + sync_interference + blocking_bound
        trace = [round(base, 9)]
        current = base
        converged = True
        interference_hp = 0.0

        for _ in range(max_iterations):
            interference_hp = 0.0
            for hp_task in hp_independent:
                if hp_task.period is None or hp_task.period <= EPSILON:
                    continue
                interference_hp += ceil(max(current, 0.0) / hp_task.period) * _task_job_cost(
                    hp_task,
                    overheads=overheads,
                )
            nxt = own_execution_cost + sync_interference + blocking_bound + interference_hp
            trace.append(round(nxt, 9))
            if abs(nxt - current) <= epsilon:
                current = nxt
                break
            current = nxt
        else:
            converged = False

        deadline = profile.deadline
        schedulable = converged and (deadline is None or current <= deadline + EPSILON)
        all_schedulable = all_schedulable and schedulable
        items.append(
            WCRTItem(
                task_id=task_id,
                wcrt=round(current, 9),
                deadline=deadline,
                schedulable=schedulable,
                iterations=trace,
            )
        )
        evidence.append(
            PlanningEvidence(
                rule="wcrt_components",
                message=f"computed WCRT for task {task_id}",
                payload={
                    "task_id": task_id,
                    "logical_task_id": profile.logical_task_id or task_id,
                    "release_index": profile.release_index,
                    "task_type": profile.task_type,
                    "wcet": round(profile.wcet, 9),
                    "dispatch_overhead": round(dispatch_overhead, 9),
                    "migration_overhead": round(migration_overhead, 9),
                    "own_execution_cost": round(own_execution_cost, 9),
                    "sync_interference": round(sync_interference, 9),
                    "sync_interference_sources": ",".join(
                        f"{source}:{round(value, 9)}"
                        for source, value in sorted(sync_sources.items())
                    ),
                    "blocking_bound": round(blocking_bound, 9),
                    "blocking_sources": ",".join(
                        f"{source}:{round(value, 9)}"
                        for source, value in sorted(blocking_sources.items())
                    ),
                    "hp_independent_count": len(hp_independent),
                    "hp_independent_tasks": ",".join(hp_names),
                    "hp_independent_job_costs": ",".join(
                        f"{source}:{value}" for source, value in sorted(hp_job_costs.items())
                    ),
                    "hp_independent_interference": round(interference_hp, 9),
                    "deadline": deadline,
                    "converged": converged,
                    "iterations": len(trace),
                },
            )
        )
        if not converged:
            evidence.append(
                PlanningEvidence(
                    rule="wcrt_not_converged",
                    message=f"WCRT iteration did not converge for task {task_id}",
                    payload={"task_id": task_id, "max_iterations": max_iterations},
                )
            )

    evidence.append(
        PlanningEvidence(
            rule="wcrt_summary",
            message="WCRT analysis summary",
            payload={
                "task_count": len(items),
                "schedulable_count": sum(1 for item in items if item.schedulable),
                "feasible": all_schedulable,
                "blocking_modeled": has_resource_blocking_model,
                "overhead_modeled": has_overhead_model,
            },
        )
    )
    return WCRTReport(
        items=items,
        feasible=all_schedulable,
        evidence=evidence,
        metadata={
            "scheduler_context": scheduler_context,
            "modeled_dimensions": [
                name
                for name, enabled in (
                    ("resource_blocking", has_resource_blocking_model),
                    ("dispatch_overhead", has_overhead_model),
                    ("migration_overhead", has_overhead_model and overheads["migration"] > EPSILON),
                    ("heterogeneous_speed", has_heterogeneous_speed_model),
                    ("etm_scaling", has_etm_scaling_model),
                )
                if enabled
            ],
            "unsupported_dimensions": _filtered_unsupported_dimensions(problem),
            "blocking_bound": "modeled" if has_resource_blocking_model else "not_applicable",
            "overhead_bound": "modeled" if has_overhead_model else "zero_or_not_applicable",
            "overheads": {key: round(value, 9) for key, value in overheads.items()},
            "etm_mode": "modeled" if has_etm_scaling_model else "constant_or_default",
        },
    )
