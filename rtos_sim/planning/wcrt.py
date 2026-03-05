"""Analytical WCRT/RTA based on static schedule tables."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from math import ceil

from .types import PlanningEvidence, PlanningProblem, ScheduleTable, WCRTItem, WCRTReport


EPSILON = 1e-12


@dataclass(slots=True)
class _TaskProfile:
    task_id: str
    task_type: str = "unknown"
    wcet: float = 0.0
    period: float | None = None
    deadline: float | None = None
    release_time: float = float("inf")
    windows_start: float | None = None
    windows_end: float | None = None
    cores: set[str] = field(default_factory=set)
    successors: set[str] = field(default_factory=set)
    predecessors: set[str] = field(default_factory=set)

    def priority_key(self) -> tuple[float, float, str]:
        deadline = self.deadline if self.deadline is not None else float("inf")
        period = self.period if self.period is not None else float("inf")
        return (deadline, period, self.task_id)

    def response_window_end(self) -> float:
        if self.windows_end is not None:
            return self.windows_end
        return self.release_time + self.wcet

    def task_window_start(self) -> float:
        if self.windows_start is not None:
            return min(self.release_time, self.windows_start)
        return self.release_time


def _build_profiles(problem: PlanningProblem, schedule_table: ScheduleTable) -> dict[str, _TaskProfile]:
    profiles: dict[str, _TaskProfile] = {}

    for segment in problem.segments:
        profile = profiles.setdefault(segment.task_id, _TaskProfile(task_id=segment.task_id))
        task_type = segment.metadata.get("task_type")
        if isinstance(task_type, str) and task_type.strip():
            profile.task_type = task_type.strip().lower()
        profile.wcet += float(segment.wcet)
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
        if segment.mapping_hint:
            profile.cores.add(segment.mapping_hint)

    segment_to_task = {segment.key: segment.task_id for segment in problem.segments}
    for segment in problem.segments:
        current_task = segment.task_id
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
        profile = profiles.setdefault(window.task_id, _TaskProfile(task_id=window.task_id))
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

    # Normalize profiles without explicit period/deadline.
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
        windows_by_task[window.task_id].append(window)

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
        hp_independent = _high_priority_independent_tasks(
            task_id,
            profiles=profiles,
            independent_map=independent_map,
        )
        hp_names = [item.task_id for item in hp_independent]

        base = profile.wcet + sync_interference
        trace = [round(base, 9)]
        current = base
        converged = True
        interference_hp = 0.0

        for _ in range(max_iterations):
            interference_hp = 0.0
            for hp_task in hp_independent:
                if hp_task.period is None or hp_task.period <= EPSILON:
                    continue
                interference_hp += ceil(max(current, 0.0) / hp_task.period) * hp_task.wcet
            nxt = profile.wcet + sync_interference + interference_hp
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
                    "task_type": profile.task_type,
                    "wcet": round(profile.wcet, 9),
                    "sync_interference": round(sync_interference, 9),
                    "sync_interference_sources": ",".join(
                        f"{source}:{round(value, 9)}"
                        for source, value in sorted(sync_sources.items())
                    ),
                    "hp_independent_count": len(hp_independent),
                    "hp_independent_tasks": ",".join(hp_names),
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
            },
        )
    )
    return WCRTReport(items=items, feasible=all_schedulable, evidence=evidence)
