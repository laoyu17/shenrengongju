"""Internal service helpers behind public planning API façades."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .heuristics import plan_static as _plan_static
from .lp_solver import plan_lp
from .normalized import NormalizedExecutionModel
from .types import PlanningProblem, PlanningResult, ScheduleTable, ScheduleWindow, WCRTReport
from .wcrt import analyze_wcrt as _analyze_wcrt


def run_static_planner(
    problem: PlanningProblem,
    *,
    planner: str,
    lp_objective: str,
    time_limit_seconds: float | None,
) -> PlanningResult:
    planner_key = planner.strip().lower()
    if planner_key in {"lp", "lp_pulp_cbc", "pulp", "cbc"}:
        return plan_lp(problem, objective=lp_objective, time_limit_seconds=time_limit_seconds)
    return _plan_static(problem, planner=planner_key)


def decorate_wcrt_report(
    report: WCRTReport,
    *,
    problem: PlanningProblem,
    normalized: NormalizedExecutionModel | None,
    task_scope: str,
    include_non_rt: bool,
    horizon: float | None,
) -> WCRTReport:
    if normalized is not None:
        modeled_dimensions = {
            str(item)
            for item in report.metadata.get("modeled_dimensions", [])
            if isinstance(item, str) and item.strip()
        }
        filtered_unsupported: list[dict[str, Any]] = []
        for item in normalized.unsupported_dimensions:
            if not isinstance(item, Mapping):
                continue
            item_id = item.get("id")
            if item_id == "resource_blocking_not_in_static_plan" and "resource_blocking" in modeled_dimensions:
                continue
            if item_id == "runtime_overheads_not_in_static_plan" and modeled_dimensions.intersection(
                {"dispatch_overhead", "migration_overhead"}
            ):
                continue
            filtered_unsupported.append(dict(item))

        remaining_ids = {
            item["id"]
            for item in filtered_unsupported
            if isinstance(item.get("id"), str)
        }
        report.metadata.update(
            {
                "semantic_fingerprint": normalized.semantic_fingerprint(),
                "planning_context": {
                    "task_scope": task_scope,
                    "include_non_rt": include_non_rt,
                    "horizon": horizon,
                    "arrival_analysis_mode": normalized.coverage_summary.get("arrival_analysis_mode"),
                },
                "coverage_summary": dict(normalized.coverage_summary),
                "arrival_assumption_trace": dict(normalized.arrival_assumption_trace),
                "assumptions": [dict(item) for item in normalized.assumptions],
                "unsupported_dimensions": filtered_unsupported,
                "blocking_bound": report.metadata.get(
                    "blocking_bound",
                    "modeled" if "resource_blocking" in modeled_dimensions else "not_applicable",
                ),
                "overhead_bound": report.metadata.get(
                    "overhead_bound",
                    "modeled"
                    if modeled_dimensions.intersection({"dispatch_overhead", "migration_overhead"})
                    else "zero_or_not_applicable",
                ),
                "heterogeneous_speed_mode": (
                    "uniform_assumed"
                    if "heterogeneous_core_speed_not_modeled" in remaining_ids
                    else (
                        "modeled"
                        if int(normalized.coverage_summary.get("effective_core_speed_count", 1) or 1) > 1
                        else "uniform_only"
                    )
                ),
            }
        )
        return report

    arrival_trace = problem.metadata.get("arrival_assumption_trace")
    if isinstance(arrival_trace, Mapping):
        report.metadata.setdefault(
            "planning_context",
            {
                "task_scope": task_scope,
                "include_non_rt": include_non_rt,
                "horizon": horizon,
                "arrival_analysis_mode": problem.metadata.get("arrival_analysis_mode"),
            },
        )
        report.metadata.setdefault("coverage_summary", dict(problem.metadata))
        report.metadata["arrival_assumption_trace"] = dict(arrival_trace)
    return report


def schedule_table_to_runtime_windows(schedule_table: ScheduleTable) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for window in sorted(
        schedule_table.windows,
        key=lambda item: (item.start_time, item.end_time, item.core_id, item.segment_key),
    ):
        rows.append(
            {
                "core_id": window.core_id,
                "segment_key": f"{window.task_id}:{window.subtask_id}:{window.segment_id}",
                "task_id": window.task_id,
                "subtask_id": window.subtask_id,
                "segment_id": window.segment_id,
                "release_index": window.release_index,
                "start": window.start_time,
                "end": window.end_time,
            }
        )
    return rows


def serialize_planning_artifact(
    result: PlanningResult,
    normalized: NormalizedExecutionModel,
    *,
    spec_fingerprint: str,
    task_scope: str,
    include_non_rt: bool,
    horizon: float | None,
    arrival_analysis_mode: str,
    arrival_envelope_min_intervals: Mapping[str, float],
) -> dict[str, Any]:
    payload = result.to_dict()
    payload.update(
        {
            "spec_fingerprint": spec_fingerprint,
            "semantic_fingerprint": normalized.semantic_fingerprint(),
            "planning_context": {
                "task_scope": task_scope,
                "include_non_rt": include_non_rt,
                "horizon": horizon,
                "planner": result.planner,
                "arrival_analysis_mode": arrival_analysis_mode,
                "arrival_envelope_min_intervals": {
                    str(task_id): float(value)
                    for task_id, value in arrival_envelope_min_intervals.items()
                },
            },
            "coverage_summary": dict(normalized.coverage_summary),
            "arrival_assumption_trace": dict(normalized.arrival_assumption_trace),
            "assumptions": [dict(item) for item in normalized.assumptions],
            "unsupported_dimensions": [dict(item) for item in normalized.unsupported_dimensions],
            "runtime_static_windows": schedule_table_to_runtime_windows(result.schedule_table),
        }
    )
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    metadata.update(
        {
            "spec_fingerprint": spec_fingerprint,
            "semantic_fingerprint": payload["semantic_fingerprint"],
            "planning_context": dict(payload["planning_context"]),
            "coverage_summary": dict(normalized.coverage_summary),
            "arrival_assumption_trace": dict(normalized.arrival_assumption_trace),
            "assumption_count": len(normalized.assumptions),
            "unsupported_dimension_count": len(normalized.unsupported_dimensions),
        }
    )
    payload["metadata"] = metadata
    return payload


def build_os_config(
    schedule_table: ScheduleTable,
    *,
    policy: str = "deadline_then_wcet",
) -> dict[str, Any]:
    if policy != "deadline_then_wcet":
        raise ValueError(f"unsupported policy: {policy}")

    windows_by_task: dict[str, list[ScheduleWindow]] = defaultdict(list)
    for window in schedule_table.windows:
        windows_by_task[window.task_id].append(window)

    ranking_rows: list[dict[str, Any]] = []
    for task_id, windows in sorted(windows_by_task.items()):
        absolute_deadline = min(
            (
                float(window.absolute_deadline)
                for window in windows
                if window.absolute_deadline is not None
            ),
            default=float("inf"),
        )
        total_wcet = sum(max(float(window.end_time) - float(window.start_time), 0.0) for window in windows)
        cores = sorted({window.core_id for window in windows})
        ranking_rows.append(
            {
                "task_id": task_id,
                "deadline": None if absolute_deadline == float("inf") else absolute_deadline,
                "deadline_sort": absolute_deadline,
                "total_wcet": round(total_wcet, 9),
                "cores": cores,
                "primary_core": cores[0] if cores else None,
                "window_count": len(windows),
            }
        )

    ranking_rows.sort(key=lambda item: (item["deadline_sort"], -item["total_wcet"], item["task_id"]))

    threads: list[dict[str, Any]] = []
    for rank, row in enumerate(ranking_rows, start=1):
        threads.append(
            {
                "task_id": row["task_id"],
                "priority": rank,
                "core_binding": list(row["cores"]),
                "primary_core": row["primary_core"],
                "window_count": row["window_count"],
                "deadline": row["deadline"],
                "total_wcet": row["total_wcet"],
            }
        )

    windows = [
        {
            "segment_key": window.segment_key,
            "task_id": window.task_id,
            "subtask_id": window.subtask_id,
            "segment_id": window.segment_id,
            "core_id": window.core_id,
            "start_time": window.start_time,
            "end_time": window.end_time,
            "release_time": window.release_time,
            "absolute_deadline": window.absolute_deadline,
        }
        for window in sorted(
            schedule_table.windows,
            key=lambda item: (item.start_time, item.end_time, item.core_id, item.segment_key),
        )
    ]

    return {
        "planner": schedule_table.planner,
        "policy": policy,
        "threads": threads,
        "schedule_windows": windows,
        "summary": {
            "core_count": len(schedule_table.core_ids),
            "window_count": len(schedule_table.windows),
            "task_count": len(threads),
            "feasible": schedule_table.feasible,
        },
    }


def evaluate_schedulability(
    problem: PlanningProblem,
    *,
    planner: str,
    lp_objective: str,
    time_limit_seconds: float | None,
    max_iterations: int,
    epsilon: float,
) -> dict[str, Any]:
    planning_result = run_static_planner(
        problem,
        planner=planner,
        lp_objective=lp_objective,
        time_limit_seconds=time_limit_seconds,
    )
    planning_feasible = bool(planning_result.feasible)
    wcrt_report = (
        _analyze_wcrt(
            problem,
            planning_result.schedule_table,
            max_iterations=max_iterations,
            epsilon=epsilon,
        )
        if planning_feasible
        else WCRTReport(items=[], feasible=False, evidence=[])
    )
    wcrt_feasible = bool(wcrt_report.feasible)
    return {
        "planning_result": planning_result,
        "wcrt_report": wcrt_report,
        "planning_feasible": planning_feasible,
        "wcrt_feasible": wcrt_feasible,
        "schedulable": planning_feasible and wcrt_feasible,
    }


@dataclass(slots=True)
class BenchmarkCaseEvaluation:
    case_report: dict[str, Any]
    baseline_pass: int
    best_pass: int
    candidate_only_pass: int
    baseline_pass_non_empty: int
    best_pass_non_empty: int
    candidate_only_pass_non_empty: int
    empty_scope_case_count: int


def evaluate_benchmark_case(
    path: Path,
    problem: PlanningProblem,
    *,
    baseline: str,
    candidates: Sequence[str],
    lp_objective: str,
    lp_time_limit_seconds: float | None,
    wcrt_max_iterations: int,
    wcrt_epsilon: float,
) -> BenchmarkCaseEvaluation:
    is_empty_scope_case = len(problem.segments) == 0
    baseline_eval = evaluate_schedulability(
        problem,
        planner=baseline,
        lp_objective=lp_objective,
        time_limit_seconds=lp_time_limit_seconds,
        max_iterations=wcrt_max_iterations,
        epsilon=wcrt_epsilon,
    )
    baseline_feasible = bool(baseline_eval["schedulable"])

    candidate_results: dict[str, dict[str, bool]] = {}
    for candidate in candidates:
        candidate_eval = evaluate_schedulability(
            problem,
            planner=candidate,
            lp_objective=lp_objective,
            time_limit_seconds=lp_time_limit_seconds,
            max_iterations=wcrt_max_iterations,
            epsilon=wcrt_epsilon,
        )
        candidate_results[candidate] = {
            "planning_feasible": bool(candidate_eval["planning_feasible"]),
            "wcrt_feasible": bool(candidate_eval["wcrt_feasible"]),
            "schedulable": bool(candidate_eval["schedulable"]),
        }

    best_candidate_feasible = baseline_feasible or any(item["schedulable"] for item in candidate_results.values())
    candidate_only_feasible = any(item["schedulable"] for item in candidate_results.values())
    return BenchmarkCaseEvaluation(
        case_report={
            "config": str(path),
            "scope_segment_count": len(problem.segments),
            "is_empty_scope_case": is_empty_scope_case,
            "baseline": baseline,
            "baseline_planning_feasible": bool(baseline_eval["planning_feasible"]),
            "baseline_wcrt_feasible": bool(baseline_eval["wcrt_feasible"]),
            "baseline_feasible": baseline_feasible,
            "candidates": candidate_results,
            "best_candidate_feasible": best_candidate_feasible,
            "candidate_only_feasible": candidate_only_feasible,
            "arrival_assumption_trace": dict(problem.metadata.get("arrival_assumption_trace", {})),
        },
        baseline_pass=int(baseline_feasible),
        best_pass=int(best_candidate_feasible),
        candidate_only_pass=int(candidate_only_feasible),
        baseline_pass_non_empty=0 if is_empty_scope_case else int(baseline_feasible),
        best_pass_non_empty=0 if is_empty_scope_case else int(best_candidate_feasible),
        candidate_only_pass_non_empty=0 if is_empty_scope_case else int(candidate_only_feasible),
        empty_scope_case_count=int(is_empty_scope_case),
    )


def finalize_benchmark_report(
    *,
    case_reports: list[dict[str, Any]],
    baseline: str,
    candidates: Sequence[str],
    resolved_scope: str,
    wcrt_max_iterations: int,
    wcrt_epsilon: float,
    arrival_analysis_mode: str | None,
    arrival_envelope_min_intervals: Mapping[str, float] | None,
    baseline_pass: int,
    best_pass: int,
    candidate_only_pass: int,
    baseline_pass_non_empty: int,
    best_pass_non_empty: int,
    candidate_only_pass_non_empty: int,
    empty_scope_case_count: int,
) -> dict[str, Any]:
    total = len(case_reports)
    baseline_rate = (baseline_pass / total) if total else 0.0
    candidate_rate = (best_pass / total) if total else 0.0
    candidate_only_rate = (candidate_only_pass / total) if total else 0.0
    non_empty_case_count = total - empty_scope_case_count
    baseline_rate_non_empty = (
        (baseline_pass_non_empty / non_empty_case_count) if non_empty_case_count else 0.0
    )
    candidate_rate_non_empty = (
        (best_pass_non_empty / non_empty_case_count) if non_empty_case_count else 0.0
    )
    candidate_only_rate_non_empty = (
        (candidate_only_pass_non_empty / non_empty_case_count) if non_empty_case_count else 0.0
    )
    uplift = (
        (candidate_rate - baseline_rate) / baseline_rate
        if baseline_rate > 1e-12
        else (1.0 if candidate_rate > 0 else 0.0)
    )
    candidate_only_uplift = (
        (candidate_only_rate - baseline_rate) / baseline_rate
        if baseline_rate > 1e-12
        else (1.0 if candidate_only_rate > 0 else 0.0)
    )
    non_empty_uplift = (
        (candidate_rate_non_empty - baseline_rate_non_empty) / baseline_rate_non_empty
        if baseline_rate_non_empty > 1e-12
        else (1.0 if candidate_rate_non_empty > 0 else 0.0)
    )
    non_empty_candidate_only_uplift = (
        (candidate_only_rate_non_empty - baseline_rate_non_empty) / baseline_rate_non_empty
        if baseline_rate_non_empty > 1e-12
        else (1.0 if candidate_only_rate_non_empty > 0 else 0.0)
    )

    resolved_arrival_mode = arrival_analysis_mode or "sample_path"
    return {
        "total_cases": total,
        "empty_scope_case_count": empty_scope_case_count,
        "non_empty_case_count": non_empty_case_count,
        "baseline": baseline,
        "candidates": list(candidates),
        "task_scope": resolved_scope,
        "wcrt_max_iterations": wcrt_max_iterations,
        "wcrt_epsilon": wcrt_epsilon,
        "arrival_analysis_mode": resolved_arrival_mode,
        "arrival_assumption_trace": {
            "arrival_analysis_mode": resolved_arrival_mode,
            "task_scope": resolved_scope,
            "detail_field": "cases[*].arrival_assumption_trace",
            "case_count": total,
        },
        "arrival_envelope_min_intervals": {
            str(task_id): float(value)
            for task_id, value in (arrival_envelope_min_intervals or {}).items()
        },
        "baseline_schedulable_rate": round(baseline_rate, 9),
        "best_candidate_schedulable_rate": round(candidate_rate, 9),
        "candidate_only_schedulable_rate": round(candidate_only_rate, 9),
        "non_empty_baseline_schedulable_rate": round(baseline_rate_non_empty, 9),
        "non_empty_best_candidate_schedulable_rate": round(candidate_rate_non_empty, 9),
        "non_empty_candidate_only_schedulable_rate": round(candidate_only_rate_non_empty, 9),
        "uplift": round(uplift, 9),
        "candidate_only_uplift": round(candidate_only_uplift, 9),
        "non_empty_uplift": round(non_empty_uplift, 9),
        "non_empty_candidate_only_uplift": round(non_empty_candidate_only_uplift, 9),
        "cases": case_reports,
    }
