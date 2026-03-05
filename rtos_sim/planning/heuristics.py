"""Offline static planning heuristics."""

from __future__ import annotations

from typing import Literal

from .types import (
    ConstraintViolation,
    PlanningEvidence,
    PlanningProblem,
    PlanningResult,
    PlanningSegment,
    ScheduleTable,
    ScheduleWindow,
)


EPSILON = 1e-12
PlannerName = Literal["np_dm", "np_edf", "precautious_dm"]


def _segment_utilization(segment: PlanningSegment, *, horizon: float | None) -> float:
    base = segment.period or segment.relative_deadline or horizon
    if base is None or base <= EPSILON:
        base = max(segment.wcet, 1.0)
    return float(segment.wcet) / float(base)


def assign_segments_wfd(
    problem: PlanningProblem,
) -> tuple[dict[str, str], list[PlanningEvidence], list[ConstraintViolation]]:
    """Assign segments to cores using worst-fit decreasing strategy."""

    assignments: dict[str, str] = {}
    evidence: list[PlanningEvidence] = []
    violations: list[ConstraintViolation] = []
    core_loads = {core_id: 0.0 for core_id in problem.core_ids}
    segment_util = {
        segment.key: _segment_utilization(segment, horizon=problem.horizon)
        for segment in problem.segments
    }

    ordered_segments = sorted(
        problem.segments,
        key=lambda item: (-segment_util[item.key], -item.wcet, item.key),
    )

    for segment in ordered_segments:
        eligible_cores = [segment.mapping_hint] if segment.mapping_hint else list(problem.core_ids)
        eligible_cores = [core_id for core_id in eligible_cores if core_id in core_loads]
        if not eligible_cores:
            violations.append(
                ConstraintViolation(
                    constraint="invalid_mapping_hint",
                    message="segment mapping_hint references unknown core",
                    segment_key=segment.key,
                    payload={"mapping_hint": segment.mapping_hint},
                )
            )
            continue
        target_core = min(eligible_cores, key=lambda core_id: (core_loads[core_id], core_id))
        before_load = core_loads[target_core]
        core_loads[target_core] += segment_util[segment.key]
        assignments[segment.key] = target_core
        evidence.append(
            PlanningEvidence(
                rule="wfd_assignment",
                message=f"assigned {segment.key} to {target_core}",
                payload={
                    "segment_key": segment.key,
                    "core_id": target_core,
                    "utilization": round(segment_util[segment.key], 8),
                    "load_before": round(before_load, 8),
                    "load_after": round(core_loads[target_core], 8),
                    "mapping_hint": segment.mapping_hint,
                },
            )
        )

    evidence.append(
        PlanningEvidence(
            rule="wfd_load_summary",
            message="core load summary after WFD assignment",
            payload={core_id: round(load, 8) for core_id, load in sorted(core_loads.items())},
        )
    )
    return assignments, evidence, violations


def _priority_key(segment: PlanningSegment, *, start_time: float, planner: PlannerName) -> tuple[float, ...]:
    absolute_deadline = (
        float(segment.absolute_deadline)
        if segment.absolute_deadline is not None
        else float("inf")
    )
    relative_deadline = (
        float(segment.relative_deadline)
        if segment.relative_deadline is not None
        else float("inf")
    )
    if planner == "np_edf":
        return (absolute_deadline, relative_deadline, segment.release_time)
    if planner in {"np_dm", "precautious_dm"}:
        return (relative_deadline, absolute_deadline, segment.release_time)
    raise ValueError(f"unsupported planner: {planner}")


def _predecessor_ready_time(
    segment: PlanningSegment,
    *,
    completion_times: dict[str, float],
) -> float:
    return max((completion_times.get(predecessor, 0.0) for predecessor in segment.predecessors), default=0.0)


def _precautious_risk_candidate(
    *,
    core_id: str,
    dispatch_start: float,
    dispatch_segment: PlanningSegment,
    completion_times: dict[str, float],
    segment_map: dict[str, PlanningSegment],
    assignments: dict[str, str],
    unscheduled: set[str],
) -> dict[str, float | str] | None:
    dispatch_finish = dispatch_start + dispatch_segment.wcet
    risky_rows: list[tuple[float, float, float, str, float]] = []

    for segment_key in sorted(unscheduled):
        if segment_key == dispatch_segment.key:
            continue
        if assignments.get(segment_key) != core_id:
            continue
        candidate = segment_map[segment_key]
        if any(predecessor not in completion_times for predecessor in candidate.predecessors):
            continue
        predecessor_ready = _predecessor_ready_time(candidate, completion_times=completion_times)
        arrival_time = max(candidate.release_time, predecessor_ready)
        if arrival_time > dispatch_finish + EPSILON:
            continue
        if candidate.absolute_deadline is None:
            continue
        predicted_finish = max(dispatch_finish, arrival_time) + candidate.wcet
        if predicted_finish <= candidate.absolute_deadline + EPSILON:
            continue
        relative_deadline = (
            float(candidate.relative_deadline)
            if candidate.relative_deadline is not None
            else float("inf")
        )
        absolute_deadline = float(candidate.absolute_deadline)
        risky_rows.append(
            (
                relative_deadline,
                absolute_deadline,
                arrival_time,
                segment_key,
                predicted_finish,
            )
        )

    if not risky_rows:
        return None
    relative_deadline, absolute_deadline, arrival_time, segment_key, predicted_finish = min(
        risky_rows,
        key=lambda item: (item[0], item[1], item[2], item[3]),
    )
    return {
        "segment_key": segment_key,
        "arrival_time": arrival_time,
        "predicted_finish": predicted_finish,
        "relative_deadline": relative_deadline,
        "absolute_deadline": absolute_deadline,
    }


def _plan_non_preemptive(problem: PlanningProblem, *, planner: PlannerName) -> PlanningResult:
    assignments, evidence, violations = assign_segments_wfd(problem)
    segment_map = problem.segment_map()
    unscheduled = {segment.key for segment in problem.segments}
    completion_times: dict[str, float] = {}
    core_available = {core_id: 0.0 for core_id in problem.core_ids}
    windows: list[ScheduleWindow] = []
    feasible = not violations

    while unscheduled:
        candidates: list[
            tuple[float, tuple[float, ...], str, str, float, float]
        ] = []

        for segment_key in sorted(unscheduled):
            segment = segment_map[segment_key]
            core_id = assignments.get(segment_key)
            if core_id is None:
                feasible = False
                violations.append(
                    ConstraintViolation(
                        constraint="missing_assignment",
                        message="segment has no core assignment",
                        segment_key=segment_key,
                    )
                )
                continue
            if any(predecessor not in completion_times for predecessor in segment.predecessors):
                continue
            predecessor_ready = _predecessor_ready_time(
                segment,
                completion_times=completion_times,
            )
            start_time = max(core_available[core_id], segment.release_time, predecessor_ready)
            priority_key = _priority_key(segment, start_time=start_time, planner=planner)
            candidates.append(
                (
                    start_time,
                    priority_key,
                    segment_key,
                    core_id,
                    predecessor_ready,
                    priority_key[0],
                )
            )

        if not candidates:
            feasible = False
            violations.append(
                ConstraintViolation(
                    constraint="precedence_unresolved",
                    message="no schedulable candidate found; check precedence graph or assignments",
                    segment_key=sorted(unscheduled)[0],
                    payload={"remaining": len(unscheduled)},
                )
            )
            break

        start_time, _, segment_key, core_id, predecessor_ready, leading_priority = min(
            candidates,
            key=lambda item: (item[0], item[1], item[2]),
        )
        selected_segment_key = segment_key
        segment = segment_map[segment_key]
        if planner == "precautious_dm":
            risk = _precautious_risk_candidate(
                core_id=core_id,
                dispatch_start=start_time,
                dispatch_segment=segment,
                completion_times=completion_times,
                segment_map=segment_map,
                assignments=assignments,
                unscheduled=unscheduled,
            )
            if risk is not None:
                risk_segment_key = str(risk["segment_key"])
                risk_arrival = float(risk["arrival_time"])
                if risk_arrival > start_time + EPSILON:
                    core_available[core_id] = risk_arrival
                    evidence.append(
                        PlanningEvidence(
                            rule="precautious_wait",
                            message=f"wait on {core_id} for risky segment {risk_segment_key}",
                            payload={
                                "core_id": core_id,
                                "wait_start": round(start_time, 8),
                                "wait_until": round(risk_arrival, 8),
                                "wait_duration": round(risk_arrival - start_time, 8),
                                "deferred_segment": segment_key,
                                "risky_segment": risk_segment_key,
                                "risky_relative_deadline": round(float(risk["relative_deadline"]), 8)
                                if float(risk["relative_deadline"]) != float("inf")
                                else None,
                                "risky_absolute_deadline": round(float(risk["absolute_deadline"]), 8),
                                "predicted_finish_if_not_wait": round(float(risk["predicted_finish"]), 8),
                            },
                        )
                    )
                    continue

                segment_key = risk_segment_key
                segment = segment_map[segment_key]
                predecessor_ready = _predecessor_ready_time(
                    segment,
                    completion_times=completion_times,
                )
                start_time = max(core_available[core_id], segment.release_time, predecessor_ready)
                leading_priority = _priority_key(segment, start_time=start_time, planner="np_dm")[0]
                evidence.append(
                    PlanningEvidence(
                        rule="precautious_risk_override",
                        message=f"override NP-DM dispatch with risky segment {segment_key}",
                        payload={
                            "core_id": core_id,
                            "override_time": round(start_time, 8),
                            "deferred_segment": selected_segment_key,
                            "risky_segment": segment_key,
                            "risky_absolute_deadline": round(float(risk["absolute_deadline"]), 8),
                            "predicted_finish_if_deferred": round(float(risk["predicted_finish"]), 8),
                        },
                    )
                )
        end_time = start_time + segment.wcet
        completion_times[segment_key] = end_time
        core_available[core_id] = end_time
        unscheduled.remove(segment_key)

        slack_before_start = None
        if segment.absolute_deadline is not None:
            slack_before_start = segment.absolute_deadline - start_time - segment.wcet
        windows.append(
            ScheduleWindow(
                segment_key=segment_key,
                task_id=segment.task_id,
                subtask_id=segment.subtask_id,
                segment_id=segment.segment_id,
                core_id=core_id,
                start_time=start_time,
                end_time=end_time,
                release_time=segment.release_time,
                absolute_deadline=segment.absolute_deadline,
                constraint_evidence={
                    "planner": planner,
                    "predecessor_ready": round(predecessor_ready, 8),
                    "priority_metric": round(leading_priority, 8)
                    if leading_priority != float("inf")
                    else None,
                    "slack_before_start": round(slack_before_start, 8)
                    if slack_before_start is not None
                    else None,
                },
            )
        )
        evidence.append(
            PlanningEvidence(
                rule="non_preemptive_dispatch",
                message=f"scheduled {segment_key} on {core_id}",
                payload={
                    "planner": planner,
                    "segment_key": segment_key,
                    "core_id": core_id,
                    "start_time": round(start_time, 8),
                    "end_time": round(end_time, 8),
                },
            )
        )

        if segment.absolute_deadline is not None and end_time > segment.absolute_deadline + EPSILON:
            feasible = False
            violations.append(
                ConstraintViolation(
                    constraint="deadline_miss",
                    message="segment execution window exceeds absolute deadline",
                    segment_key=segment_key,
                    payload={
                        "absolute_deadline": segment.absolute_deadline,
                        "finish_time": round(end_time, 8),
                    },
                )
            )

    windows.sort(key=lambda item: (item.start_time, item.end_time, item.core_id, item.segment_key))
    schedule_table = ScheduleTable(
        planner=planner,
        core_ids=list(problem.core_ids),
        windows=windows,
        feasible=feasible and not unscheduled,
        violations=violations,
        evidence=evidence,
    )
    return PlanningResult(
        planner=planner,
        schedule_table=schedule_table,
        feasible=schedule_table.feasible,
        assignments=assignments,
        unscheduled_segments=sorted(unscheduled),
        metadata={
            "segment_count": len(problem.segments),
            "scheduled_count": len(windows),
        },
    )


def plan_np_dm(problem: PlanningProblem) -> PlanningResult:
    return _plan_non_preemptive(problem, planner="np_dm")


def plan_np_edf(problem: PlanningProblem) -> PlanningResult:
    return _plan_non_preemptive(problem, planner="np_edf")


def plan_precautious_dm(problem: PlanningProblem) -> PlanningResult:
    return _plan_non_preemptive(problem, planner="precautious_dm")


def plan_static(problem: PlanningProblem, planner: str = "np_edf") -> PlanningResult:
    key = planner.strip().lower()
    if key == "np_dm":
        return plan_np_dm(problem)
    if key == "np_edf":
        return plan_np_edf(problem)
    if key in {"precautious", "precautious_dm"}:
        return plan_precautious_dm(problem)
    raise ValueError(f"unsupported planner: {planner}")
