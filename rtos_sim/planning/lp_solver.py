"""MILP-based static planning solver using PuLP + CBC."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Literal

from .types import (
    ConstraintViolation,
    PlanningEvidence,
    PlanningProblem,
    PlanningResult,
    ScheduleTable,
    ScheduleWindow,
    eligible_core_ids_for_segment,
    execution_cost_for_core,
    max_execution_cost,
    min_execution_cost,
)


EPSILON = 1e-12
LPObjective = Literal["response_time", "spread_execution"]


def _load_pulp() -> Any:
    import pulp

    return pulp


@dataclass(slots=True)
class _PrecheckResult:
    violations: list[ConstraintViolation]
    graph: dict[str, list[str]]
    in_degree: dict[str, int]


def _precheck_problem(problem: PlanningProblem) -> _PrecheckResult:
    segment_map = problem.segment_map()
    graph: dict[str, list[str]] = defaultdict(list)
    in_degree = {segment.key: 0 for segment in problem.segments}
    violations: list[ConstraintViolation] = []

    for segment in problem.segments:
        eligible_cores = eligible_core_ids_for_segment(segment, problem.core_ids)
        if not eligible_cores:
            violations.append(
                ConstraintViolation(
                    constraint="invalid_mapping_hint",
                    message="segment mapping_hint references unknown core",
                    segment_key=segment.key,
                    payload={"mapping_hint": segment.mapping_hint},
                )
            )
        if segment.absolute_deadline is not None:
            budget = float(segment.absolute_deadline) - float(segment.release_time)
            min_cost = min_execution_cost(segment, problem.core_ids)
            if budget + EPSILON < float(min_cost):
                violations.append(
                    ConstraintViolation(
                        constraint="deadline_window_too_small",
                        message="segment execution cost exceeds release-to-deadline window",
                        segment_key=segment.key,
                        payload={
                            "release_time": segment.release_time,
                            "absolute_deadline": segment.absolute_deadline,
                            "execution_cost": min_cost,
                        },
                    )
                )
        for predecessor in segment.predecessors:
            if predecessor not in segment_map:
                violations.append(
                    ConstraintViolation(
                        constraint="unknown_predecessor",
                        message="predecessor segment key does not exist",
                        segment_key=segment.key,
                        payload={"predecessor": predecessor},
                    )
                )
                continue
            graph[predecessor].append(segment.key)
            in_degree[segment.key] += 1

    # Detect precedence cycles (Kahn).
    queue = deque(sorted(key for key, degree in in_degree.items() if degree == 0))
    visited = 0
    degrees = dict(in_degree)
    while queue:
        key = queue.popleft()
        visited += 1
        for child in graph.get(key, []):
            degrees[child] -= 1
            if degrees[child] == 0:
                queue.append(child)
    if visited != len(in_degree):
        cycle_candidates = sorted(key for key, degree in degrees.items() if degree > 0)
        violations.append(
            ConstraintViolation(
                constraint="precedence_cycle",
                message="precedence graph contains at least one cycle",
                payload={
                    "cycle_candidates": ",".join(cycle_candidates[:16]),
                    "candidate_count": len(cycle_candidates),
                },
            )
        )

    return _PrecheckResult(violations=violations, graph=dict(graph), in_degree=in_degree)


def _build_failed_result(
    problem: PlanningProblem,
    *,
    planner: str,
    violations: list[ConstraintViolation],
    evidence: list[PlanningEvidence] | None = None,
    metadata: dict[str, object] | None = None,
) -> PlanningResult:
    table = ScheduleTable(
        planner=planner,
        core_ids=list(problem.core_ids),
        windows=[],
        feasible=False,
        violations=violations,
        evidence=list(evidence or []),
    )
    return PlanningResult(
        planner=planner,
        schedule_table=table,
        feasible=False,
        assignments={},
        unscheduled_segments=sorted(segment.key for segment in problem.segments),
        metadata=dict(metadata or {}),
    )


def _estimate_big_m(problem: PlanningProblem) -> float:
    total_wcet = sum(max_execution_cost(segment, problem.core_ids) for segment in problem.segments)
    max_release = max((float(segment.release_time) for segment in problem.segments), default=0.0)
    max_deadline = max(
        (
            float(segment.absolute_deadline)
            for segment in problem.segments
            if segment.absolute_deadline is not None
        ),
        default=0.0,
    )
    horizon = float(problem.horizon) if problem.horizon is not None else 0.0
    return max(total_wcet + max_release, max_deadline, horizon, 1.0) + total_wcet + 1.0


def plan_lp(
    problem: PlanningProblem,
    *,
    objective: LPObjective = "response_time",
    time_limit_seconds: float | None = 30.0,
) -> PlanningResult:
    """Solve static planning using MILP constraints and PuLP CBC backend."""

    planner_name = "lp_pulp_cbc"
    precheck = _precheck_problem(problem)
    if precheck.violations:
        return _build_failed_result(
            problem,
            planner=planner_name,
            violations=precheck.violations,
            evidence=[
                PlanningEvidence(
                    rule="lp_precheck_failed",
                    message="precheck detected infeasible or invalid inputs",
                    payload={"violation_count": len(precheck.violations)},
                )
            ],
            metadata={"objective": objective, "phase": "precheck"},
        )

    try:
        pulp = _load_pulp()
    except Exception as exc:  # noqa: BLE001
        return _build_failed_result(
            problem,
            planner=planner_name,
            violations=[
                ConstraintViolation(
                    constraint="solver_unavailable",
                    message="failed to import PuLP runtime",
                    payload={"error": str(exc)},
                )
            ],
            evidence=[
                PlanningEvidence(
                    rule="lp_solver_import",
                    message="PuLP import failed before model construction",
                    payload={"error": str(exc)},
                )
            ],
            metadata={"objective": objective, "phase": "import"},
        )

    if objective not in {"response_time", "spread_execution"}:
        return _build_failed_result(
            problem,
            planner=planner_name,
            violations=[
                ConstraintViolation(
                    constraint="invalid_objective",
                    message="unsupported LP objective",
                    payload={"objective": str(objective)},
                )
            ],
            metadata={"objective": str(objective), "phase": "input"},
        )

    segment_map = problem.segment_map()
    segment_keys = sorted(segment_map)
    core_ids = list(problem.core_ids)
    big_m = _estimate_big_m(problem)
    duration_by_assignment = {
        (key, core_id): execution_cost_for_core(segment_map[key], core_id)
        for key in segment_keys
        for core_id in core_ids
    }

    model = pulp.LpProblem("rtos_sim_static_planning_lp", pulp.LpMinimize)
    start_vars = {
        key: pulp.LpVariable(f"s_{index}", lowBound=0, cat="Continuous")
        for index, key in enumerate(segment_keys)
    }
    end_vars = {
        key: pulp.LpVariable(f"e_{index}", lowBound=0, cat="Continuous")
        for index, key in enumerate(segment_keys)
    }
    assign_vars = {
        (key, core_id): pulp.LpVariable(
            f"x_{segment_idx}_{core_idx}", lowBound=0, upBound=1, cat="Binary"
        )
        for segment_idx, key in enumerate(segment_keys)
        for core_idx, core_id in enumerate(core_ids)
    }
    order_vars = {
        (left, right, core_id): pulp.LpVariable(
            f"ord_{pair_idx}_{core_idx}", lowBound=0, upBound=1, cat="Binary"
        )
        for pair_idx, (left, right) in enumerate(combinations(segment_keys, 2))
        for core_idx, core_id in enumerate(core_ids)
    }

    for key in segment_keys:
        segment = segment_map[key]
        model += end_vars[key] == start_vars[key] + pulp.lpSum(
            duration_by_assignment[(key, core_id)] * assign_vars[(key, core_id)]
            for core_id in core_ids
        ), f"duration_{key}"
        model += (
            pulp.lpSum(assign_vars[(key, core_id)] for core_id in core_ids) == 1
        ), f"assign_once_{key}"
        model += start_vars[key] >= float(segment.release_time), f"release_{key}"
        if segment.absolute_deadline is not None:
            model += end_vars[key] <= float(segment.absolute_deadline), f"deadline_{key}"
        if segment.mapping_hint is not None:
            for core_id in core_ids:
                value = 1 if core_id == segment.mapping_hint else 0
                model += assign_vars[(key, core_id)] == value, f"mapping_{key}_{core_id}"
        for predecessor in segment.predecessors:
            model += start_vars[key] >= end_vars[predecessor], f"precedence_{predecessor}_to_{key}"

    for left, right in combinations(segment_keys, 2):
        for core_id in core_ids:
            order = order_vars[(left, right, core_id)]
            left_assign = assign_vars[(left, core_id)]
            right_assign = assign_vars[(right, core_id)]
            # If two segments are assigned to the same core, one must end before the other starts.
            model += (
                end_vars[left]
                <= start_vars[right] + big_m * (1 - order) + big_m * (2 - left_assign - right_assign)
            ), f"nonoverlap_l_{left}_{right}_{core_id}"
            model += (
                end_vars[right]
                <= start_vars[left] + big_m * order + big_m * (2 - left_assign - right_assign)
            ), f"nonoverlap_r_{left}_{right}_{core_id}"

    if objective == "response_time":
        model += pulp.lpSum(
            end_vars[key] - float(segment_map[key].release_time) for key in segment_keys
        )
    else:
        load_vars = {
            core_id: pulp.LpVariable(f"load_{core_idx}", lowBound=0, cat="Continuous")
            for core_idx, core_id in enumerate(core_ids)
        }
        max_load = pulp.LpVariable("max_load", lowBound=0, cat="Continuous")
        for core_id in core_ids:
            model += load_vars[core_id] == pulp.lpSum(
                duration_by_assignment[(key, core_id)] * assign_vars[(key, core_id)] for key in segment_keys
            ), f"load_eq_{core_id}"
            model += load_vars[core_id] <= max_load, f"load_cap_{core_id}"
        model += max_load * 1000 + pulp.lpSum(
            end_vars[key] - float(segment_map[key].release_time) for key in segment_keys
        )

    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit_seconds)
    model.solve(solver)
    status_code = int(model.status)
    status_name = str(pulp.LpStatus.get(status_code, status_code))

    evidence = [
        PlanningEvidence(
            rule="lp_solve_status",
            message="PuLP solve completed",
            payload={
                "objective": objective,
                "status": status_name,
                "status_code": status_code,
                "time_limit_seconds": time_limit_seconds,
                "big_m": round(big_m, 8),
            },
        )
    ]

    if status_name not in {"Optimal"}:
        return _build_failed_result(
            problem,
            planner=planner_name,
            violations=[
                ConstraintViolation(
                    constraint="solver_status",
                    message="LP solver did not return an optimal solution",
                    payload={"status": status_name, "status_code": status_code},
                )
            ],
            evidence=evidence,
            metadata={"objective": objective, "phase": "solve"},
        )

    assignments: dict[str, str] = {}
    windows: list[ScheduleWindow] = []
    for key in segment_keys:
        assigned_core = None
        for core_id in core_ids:
            value = float(assign_vars[(key, core_id)].value() or 0.0)
            if value > 0.5:
                assigned_core = core_id
                break
        if assigned_core is None:
            return _build_failed_result(
                problem,
                planner=planner_name,
                violations=[
                    ConstraintViolation(
                        constraint="assignment_extract_failed",
                        message="LP result did not produce a valid core assignment",
                        segment_key=key,
                    )
                ],
                evidence=evidence,
                metadata={"objective": objective, "phase": "extract"},
            )
        assignments[key] = assigned_core
        segment = segment_map[key]
        start_time = float(start_vars[key].value() or 0.0)
        end_time = float(end_vars[key].value() or 0.0)
        windows.append(
            ScheduleWindow(
                segment_key=key,
                task_id=segment.task_id,
                subtask_id=segment.subtask_id,
                segment_id=segment.segment_id,
                core_id=assigned_core,
                release_index=segment.release_index,
                start_time=start_time,
                end_time=end_time,
                release_time=segment.release_time,
                absolute_deadline=segment.absolute_deadline,
                constraint_evidence={
                    "objective": objective,
                    "solver_status": status_name,
                },
            )
        )

    windows.sort(key=lambda item: (item.start_time, item.end_time, item.core_id, item.segment_key))
    schedule = ScheduleTable(
        planner=planner_name,
        core_ids=list(core_ids),
        windows=windows,
        feasible=True,
        violations=[],
        evidence=evidence,
    )
    return PlanningResult(
        planner=planner_name,
        schedule_table=schedule,
        feasible=True,
        assignments=assignments,
        unscheduled_segments=[],
        metadata={"objective": objective, "phase": "solve"},
    )
