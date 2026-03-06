"""Public service API for offline planning, WCRT analysis and exports."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from rtos_sim.io import ConfigLoader
from rtos_sim.model import ModelSpec
from rtos_sim.planning import (
    ConstraintViolation,
    DEFAULT_TASK_SCOPE,
    PlanningEvidence,
    PlanningProblem,
    PlanningResult,
    ScheduleTable,
    ScheduleWindow,
    WCRTReport,
    analyze_wcrt as _analyze_wcrt,
    build_normalized_execution_model,
    normalize_task_scope,
    plan_lp,
    plan_static as _plan_static,
)


DEFAULT_PLANNING_SECTION: dict[str, Any] = {
    "enabled": False,
    "planner": "np_edf",
    "lp_objective": "response_time",
    "task_scope": DEFAULT_TASK_SCOPE,
    "include_non_rt": False,
    "params": {},
}


def planning_defaults() -> dict[str, Any]:
    """Return default planning section values for config migration."""

    return {
        "enabled": DEFAULT_PLANNING_SECTION["enabled"],
        "planner": DEFAULT_PLANNING_SECTION["planner"],
        "lp_objective": DEFAULT_PLANNING_SECTION["lp_objective"],
        "task_scope": DEFAULT_PLANNING_SECTION["task_scope"],
        "include_non_rt": DEFAULT_PLANNING_SECTION["include_non_rt"],
        "params": dict(DEFAULT_PLANNING_SECTION["params"]),
    }


def _as_model_spec(spec_or_payload: ModelSpec | Mapping[str, Any]) -> ModelSpec:
    if isinstance(spec_or_payload, ModelSpec):
        return spec_or_payload
    return ConfigLoader().load_data(dict(spec_or_payload))


def apply_planning_overrides(
    spec_or_payload: ModelSpec | Mapping[str, Any],
    *,
    arrival_analysis_mode: str | None = None,
    arrival_envelope_min_intervals: Mapping[str, float] | None = None,
) -> ModelSpec:
    """Return a spec copy with planning override params merged in."""

    spec = _as_model_spec(spec_or_payload)
    if arrival_analysis_mode is None and not arrival_envelope_min_intervals:
        return spec

    payload = spec.model_dump(mode="json", by_alias=True, exclude_none=True)
    planning_payload = payload.setdefault("planning", planning_defaults())
    if not isinstance(planning_payload, dict):
        planning_payload = planning_defaults()
        payload["planning"] = planning_payload
    params = planning_payload.setdefault("params", {})
    if not isinstance(params, dict):
        params = {}
        planning_payload["params"] = params
    if arrival_analysis_mode is not None:
        params["arrival_analysis_mode"] = str(arrival_analysis_mode).strip().lower()
    if arrival_envelope_min_intervals:
        params["arrival_envelope_min_intervals"] = {
            str(task_id): float(value)
            for task_id, value in arrival_envelope_min_intervals.items()
        }
    return ConfigLoader().load_data(payload)


def model_spec_fingerprint(spec_or_payload: ModelSpec | Mapping[str, Any]) -> str:
    """Build stable SHA-256 fingerprint for semantic-equivalent model specs."""

    spec = _as_model_spec(spec_or_payload)
    canonical_payload = spec.model_dump(mode="json", by_alias=True, exclude_none=False)
    canonical_json = json.dumps(canonical_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def extract_plan_spec_fingerprint(payload: Mapping[str, Any]) -> str | None:
    """Read spec fingerprint from plan JSON payload (top-level or metadata)."""

    for key in ("spec_fingerprint", "spec_signature"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        for key in ("spec_fingerprint", "spec_signature"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def semantic_model_fingerprint(
    spec_or_payload: ModelSpec | Mapping[str, Any],
    *,
    task_scope: str | None = None,
    include_non_rt: bool = False,
    horizon: float | None = None,
    arrival_analysis_mode: str | None = None,
    arrival_envelope_min_intervals: Mapping[str, float] | None = None,
) -> str:
    """Build semantic fingerprint for the normalized planning/runtime projection."""

    spec = apply_planning_overrides(
        spec_or_payload,
        arrival_analysis_mode=arrival_analysis_mode,
        arrival_envelope_min_intervals=arrival_envelope_min_intervals,
    )
    normalized = build_normalized_execution_model(
        spec,
        task_scope=task_scope,
        include_non_rt=include_non_rt,
        horizon=horizon,
    )
    return normalized.semantic_fingerprint()


def extract_plan_semantic_fingerprint(payload: Mapping[str, Any]) -> str | None:
    """Read semantic fingerprint from plan JSON payload."""

    value = payload.get("semantic_fingerprint")
    if isinstance(value, str) and value.strip():
        return value.strip()
    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        value = metadata.get("semantic_fingerprint")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def extract_plan_planning_context(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Read planning-context fields from plan JSON payload."""

    context_payload = payload.get("planning_context")
    if not isinstance(context_payload, Mapping):
        metadata = payload.get("metadata")
        if isinstance(metadata, Mapping):
            nested = metadata.get("planning_context")
            context_payload = nested if isinstance(nested, Mapping) else metadata

    task_scope = context_payload.get("task_scope") if isinstance(context_payload, Mapping) else None
    include_non_rt = context_payload.get("include_non_rt") if isinstance(context_payload, Mapping) else False
    horizon = context_payload.get("horizon") if isinstance(context_payload, Mapping) else None
    planner = context_payload.get("planner") if isinstance(context_payload, Mapping) else None
    arrival_analysis_mode = (
        context_payload.get("arrival_analysis_mode") if isinstance(context_payload, Mapping) else None
    )
    arrival_envelope_min_intervals = (
        context_payload.get("arrival_envelope_min_intervals") if isinstance(context_payload, Mapping) else None
    )

    resolved_horizon: float | None
    if horizon in (None, ""):
        resolved_horizon = None
    else:
        resolved_horizon = float(horizon)

    resolved_envelope: dict[str, float] = {}
    if isinstance(arrival_envelope_min_intervals, Mapping):
        for task_id, value in arrival_envelope_min_intervals.items():
            if isinstance(task_id, str) and isinstance(value, (int, float)):
                resolved_envelope[task_id] = float(value)

    return {
        "task_scope": str(task_scope or DEFAULT_PLANNING_SECTION["task_scope"]),
        "include_non_rt": bool(include_non_rt),
        "horizon": resolved_horizon,
        "planner": str(planner) if isinstance(planner, str) and planner.strip() else None,
        "arrival_analysis_mode": (
            str(arrival_analysis_mode).strip().lower()
            if isinstance(arrival_analysis_mode, str) and arrival_analysis_mode.strip()
            else None
        ),
        "arrival_envelope_min_intervals": resolved_envelope,
    }


def plan_fingerprint_expectations(
    spec_or_payload: ModelSpec | Mapping[str, Any],
    plan_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Compute expected/actual plan fingerprint values for one spec."""

    spec = _as_model_spec(spec_or_payload)
    context = extract_plan_planning_context(plan_payload)
    semantic_spec = apply_planning_overrides(
        spec,
        arrival_analysis_mode=(
            str(context["arrival_analysis_mode"])
            if isinstance(context.get("arrival_analysis_mode"), str)
            else None
        ),
        arrival_envelope_min_intervals=(
            context["arrival_envelope_min_intervals"]
            if isinstance(context.get("arrival_envelope_min_intervals"), Mapping)
            else None
        ),
    )
    return {
        "expected_spec_fingerprint": model_spec_fingerprint(spec),
        "actual_spec_fingerprint": extract_plan_spec_fingerprint(plan_payload),
        "expected_semantic_fingerprint": semantic_model_fingerprint(
            semantic_spec,
            task_scope=str(context["task_scope"]),
            include_non_rt=bool(context["include_non_rt"]),
            horizon=context["horizon"],
            arrival_analysis_mode=(
                str(context["arrival_analysis_mode"])
                if isinstance(context.get("arrival_analysis_mode"), str)
                else None
            ),
            arrival_envelope_min_intervals=(
                context["arrival_envelope_min_intervals"]
                if isinstance(context.get("arrival_envelope_min_intervals"), Mapping)
                else None
            ),
        ),
        "actual_semantic_fingerprint": extract_plan_semantic_fingerprint(plan_payload),
        "planning_context": context,
    }


def build_planning_problem(
    spec_or_payload: ModelSpec | Mapping[str, Any],
    *,
    task_scope: str | None = None,
    include_non_rt: bool = False,
    horizon: float | None = None,
    arrival_analysis_mode: str | None = None,
    arrival_envelope_min_intervals: Mapping[str, float] | None = None,
) -> PlanningProblem:
    spec = apply_planning_overrides(
        spec_or_payload,
        arrival_analysis_mode=arrival_analysis_mode,
        arrival_envelope_min_intervals=arrival_envelope_min_intervals,
    )
    normalized = build_normalized_execution_model(
        spec,
        task_scope=task_scope,
        include_non_rt=include_non_rt,
        horizon=horizon,
    )
    return normalized.to_planning_problem()


def _run_static_planner(
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


def plan_static(
    spec_or_problem: ModelSpec | Mapping[str, Any] | PlanningProblem,
    *,
    planner: str = "np_edf",
    task_scope: str | None = None,
    include_non_rt: bool = False,
    horizon: float | None = None,
    lp_objective: str = "response_time",
    time_limit_seconds: float | None = 30.0,
    arrival_analysis_mode: str | None = None,
    arrival_envelope_min_intervals: Mapping[str, float] | None = None,
) -> PlanningResult:
    """Plan a static schedule table from spec/problem input."""

    if isinstance(spec_or_problem, PlanningProblem):
        problem = spec_or_problem
    else:
        problem = build_planning_problem(
            spec_or_problem,
            task_scope=task_scope,
            include_non_rt=include_non_rt,
            horizon=horizon,
            arrival_analysis_mode=arrival_analysis_mode,
            arrival_envelope_min_intervals=arrival_envelope_min_intervals,
        )
    return _run_static_planner(
        problem,
        planner=planner,
        lp_objective=lp_objective,
        time_limit_seconds=time_limit_seconds,
    )


def analyze_wcrt(
    spec_or_problem: ModelSpec | Mapping[str, Any] | PlanningProblem,
    schedule_table: ScheduleTable,
    *,
    task_scope: str | None = None,
    include_non_rt: bool = False,
    horizon: float | None = None,
    max_iterations: int = 64,
    epsilon: float = 1e-9,
    arrival_analysis_mode: str | None = None,
    arrival_envelope_min_intervals: Mapping[str, float] | None = None,
) -> WCRTReport:
    """Run analytical WCRT based on a schedule table."""

    if isinstance(spec_or_problem, PlanningProblem):
        problem = spec_or_problem
    else:
        problem = build_planning_problem(
            spec_or_problem,
            task_scope=task_scope,
            include_non_rt=include_non_rt,
            horizon=horizon,
            arrival_analysis_mode=arrival_analysis_mode,
            arrival_envelope_min_intervals=arrival_envelope_min_intervals,
        )
    report = _analyze_wcrt(
        problem,
        schedule_table,
        max_iterations=max_iterations,
        epsilon=epsilon,
    )
    if isinstance(spec_or_problem, PlanningProblem):
        resolved_scope = str(problem.metadata.get("task_scope", DEFAULT_TASK_SCOPE))
        resolved_include_non_rt = bool(problem.metadata.get("include_non_rt", include_non_rt))
        resolved_horizon = horizon if horizon is not None else problem.horizon
        normalized = None
    else:
        spec = _as_model_spec(spec_or_problem)
        resolved_scope = normalize_task_scope(task_scope, include_non_rt=include_non_rt)
        resolved_include_non_rt = bool(include_non_rt or resolved_scope == "all")
        resolved_horizon = horizon
        normalized = build_normalized_execution_model(
            spec,
            task_scope=resolved_scope,
            include_non_rt=resolved_include_non_rt,
            horizon=resolved_horizon,
        )

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
            if item_id == "runtime_overheads_not_in_static_plan" and modeled_dimensions.intersection({"dispatch_overhead", "migration_overhead"}):
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
                    "task_scope": resolved_scope,
                    "include_non_rt": resolved_include_non_rt,
                    "horizon": resolved_horizon,
                },
                "coverage_summary": dict(normalized.coverage_summary),
                "assumptions": [dict(item) for item in normalized.assumptions],
                "unsupported_dimensions": filtered_unsupported,
                "blocking_bound": report.metadata.get(
                    "blocking_bound",
                    "modeled" if "resource_blocking" in modeled_dimensions else "not_applicable",
                ),
                "overhead_bound": report.metadata.get(
                    "overhead_bound",
                    "modeled" if modeled_dimensions.intersection({"dispatch_overhead", "migration_overhead"}) else "zero_or_not_applicable",
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


def schedule_table_from_dict(payload: Mapping[str, Any]) -> ScheduleTable:
    """Parse `ScheduleTable` from serialized JSON payload."""

    windows: list[ScheduleWindow] = []
    for row in payload.get("windows", []):
        if not isinstance(row, Mapping):
            continue
        windows.append(
            ScheduleWindow(
                segment_key=str(row.get("segment_key", "")),
                task_id=str(row.get("task_id", "")),
                subtask_id=str(row.get("subtask_id", "")),
                segment_id=str(row.get("segment_id", "")),
                core_id=str(row.get("core_id", "")),
                start_time=float(row.get("start_time", 0.0)),
                end_time=float(row.get("end_time", 0.0)),
                release_time=float(row.get("release_time", 0.0)),
                absolute_deadline=(
                    float(row["absolute_deadline"])
                    if row.get("absolute_deadline") is not None
                    else None
                ),
                release_index=(
                    int(row["release_index"])
                    if row.get("release_index") is not None
                    else None
                ),
                constraint_evidence=dict(row.get("constraint_evidence", {})),
            )
        )

    violations: list[ConstraintViolation] = []
    for item in payload.get("violations", []):
        if not isinstance(item, Mapping):
            continue
        violations.append(
            ConstraintViolation(
                constraint=str(item.get("constraint", "")),
                message=str(item.get("message", "")),
                segment_key=(
                    str(item["segment_key"]) if item.get("segment_key") is not None else None
                ),
                payload=dict(item.get("payload", {})),
            )
        )

    evidence: list[PlanningEvidence] = []
    for item in payload.get("evidence", []):
        if not isinstance(item, Mapping):
            continue
        evidence.append(
            PlanningEvidence(
                rule=str(item.get("rule", "")),
                message=str(item.get("message", "")),
                payload=dict(item.get("payload", {})),
            )
        )

    return ScheduleTable(
        planner=str(payload.get("planner", "unknown")),
        core_ids=[str(core_id) for core_id in payload.get("core_ids", [])],
        windows=windows,
        feasible=bool(payload.get("feasible", False)),
        violations=violations,
        evidence=evidence,
    )


def planning_result_from_dict(payload: Mapping[str, Any]) -> PlanningResult:
    """Parse `PlanningResult` from serialized JSON payload."""

    schedule_payload = payload.get("schedule_table")
    if not isinstance(schedule_payload, Mapping):
        raise ValueError("planning result missing schedule_table object")
    schedule_table = schedule_table_from_dict(schedule_payload)
    metadata = dict(payload.get("metadata", {}))
    plan_fingerprint = extract_plan_spec_fingerprint(payload)
    if plan_fingerprint and "spec_fingerprint" not in metadata:
        metadata["spec_fingerprint"] = plan_fingerprint
    semantic_fingerprint = extract_plan_semantic_fingerprint(payload)
    if semantic_fingerprint and "semantic_fingerprint" not in metadata:
        metadata["semantic_fingerprint"] = semantic_fingerprint
    planning_context = payload.get("planning_context")
    if isinstance(planning_context, Mapping) and "planning_context" not in metadata:
        metadata["planning_context"] = dict(planning_context)
    coverage_summary = payload.get("coverage_summary")
    if isinstance(coverage_summary, Mapping) and "coverage_summary" not in metadata:
        metadata["coverage_summary"] = dict(coverage_summary)
    return PlanningResult(
        planner=str(payload.get("planner", schedule_table.planner)),
        schedule_table=schedule_table,
        feasible=bool(payload.get("feasible", schedule_table.feasible)),
        assignments={
            str(segment_key): str(core_id)
            for segment_key, core_id in dict(payload.get("assignments", {})).items()
        },
        unscheduled_segments=[
            str(segment_key) for segment_key in payload.get("unscheduled_segments", [])
        ],
        metadata=metadata,
    )


def serialize_planning_result(
    result: PlanningResult,
    *,
    spec_or_payload: ModelSpec | Mapping[str, Any],
    task_scope: str | None = None,
    include_non_rt: bool = False,
    horizon: float | None = None,
) -> dict[str, Any]:
    """Serialize planning result into a unified artifact for CLI/UI/runtime reuse."""

    spec = _as_model_spec(spec_or_payload)
    resolved_scope = normalize_task_scope(task_scope, include_non_rt=include_non_rt)
    resolved_include_non_rt = bool(include_non_rt or resolved_scope == "all")
    planning_params = spec.planning.params if spec.planning is not None and isinstance(spec.planning.params, dict) else {}
    arrival_analysis_mode = str(planning_params.get("arrival_analysis_mode", "sample_path") or "sample_path")
    raw_envelope = planning_params.get("arrival_envelope_min_intervals", {})
    arrival_envelope_min_intervals = (
        {
            str(task_id): float(value)
            for task_id, value in raw_envelope.items()
            if isinstance(task_id, str) and isinstance(value, (int, float))
        }
        if isinstance(raw_envelope, dict)
        else {}
    )
    normalized = build_normalized_execution_model(
        spec,
        task_scope=resolved_scope,
        include_non_rt=resolved_include_non_rt,
        horizon=horizon,
    )
    spec_fingerprint = model_spec_fingerprint(spec)
    semantic_fingerprint = normalized.semantic_fingerprint()
    payload = result.to_dict()
    payload.update(
        {
            "spec_fingerprint": spec_fingerprint,
            "semantic_fingerprint": semantic_fingerprint,
            "planning_context": {
                "task_scope": resolved_scope,
                "include_non_rt": resolved_include_non_rt,
                "horizon": horizon,
                "planner": result.planner,
                "arrival_analysis_mode": arrival_analysis_mode,
                "arrival_envelope_min_intervals": arrival_envelope_min_intervals,
            },
            "coverage_summary": dict(normalized.coverage_summary),
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
            "semantic_fingerprint": semantic_fingerprint,
            "planning_context": dict(payload["planning_context"]),
            "coverage_summary": dict(normalized.coverage_summary),
            "assumption_count": len(normalized.assumptions),
            "unsupported_dimension_count": len(normalized.unsupported_dimensions),
        }
    )
    payload["metadata"] = metadata
    return payload


def export_os_config(
    schedule_table: ScheduleTable,
    *,
    policy: str = "deadline_then_wcet",
) -> dict[str, Any]:
    """Export thread priorities, core bindings and static windows."""

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


def schedule_table_to_runtime_windows(schedule_table: ScheduleTable) -> list[dict[str, Any]]:
    """Convert planning `ScheduleTable` windows to runtime static-window config rows."""

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


def extract_plan_runtime_windows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Read runtime static windows from unified plan artifact."""

    rows = payload.get("runtime_static_windows")
    if isinstance(rows, list):
        return [dict(row) for row in rows if isinstance(row, Mapping)]
    schedule_payload = payload.get("schedule_table")
    if isinstance(schedule_payload, Mapping):
        return schedule_table_to_runtime_windows(schedule_table_from_dict(schedule_payload))
    return []


def materialize_runtime_spec_from_plan(
    spec_or_payload: ModelSpec | Mapping[str, Any],
    plan_payload: Mapping[str, Any],
) -> ModelSpec:
    """Inject plan runtime windows into scheduler.params and re-validate the spec."""

    if not bool(plan_payload.get("feasible", False)):
        raise ValueError("plan-json is infeasible and cannot be materialized for runtime execution")

    runtime_windows = extract_plan_runtime_windows(plan_payload)
    if not runtime_windows:
        raise ValueError("plan-json does not contain runtime_static_windows")

    spec = _as_model_spec(spec_or_payload)
    payload = spec.model_dump(mode="json", by_alias=True, exclude_none=True)
    scheduler_payload = payload.setdefault("scheduler", {})
    if not isinstance(scheduler_payload, dict):
        raise ValueError("invalid scheduler payload while materializing runtime plan")
    params = scheduler_payload.setdefault("params", {})
    if not isinstance(params, dict):
        raise ValueError("invalid scheduler.params payload while materializing runtime plan")
    params["static_window_mode"] = True
    params["static_windows"] = runtime_windows
    return ConfigLoader().load_data(payload)


def plan_and_analyze_schedulability(
    spec_or_problem: ModelSpec | Mapping[str, Any] | PlanningProblem,
    *,
    planner: str = "np_edf",
    task_scope: str | None = None,
    include_non_rt: bool = False,
    horizon: float | None = None,
    lp_objective: str = "response_time",
    time_limit_seconds: float | None = 30.0,
    max_iterations: int = 64,
    epsilon: float = 1e-9,
) -> dict[str, Any]:
    """Evaluate schedulability using static-plan feasibility + WCRT feasibility."""

    if isinstance(spec_or_problem, PlanningProblem):
        problem = spec_or_problem
    else:
        problem = build_planning_problem(
            spec_or_problem,
            task_scope=task_scope,
            include_non_rt=include_non_rt,
            horizon=horizon,
        )

    planning_result = _run_static_planner(
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


def benchmark_sched_rate(
    config_paths: Sequence[str | Path],
    *,
    baseline: str = "np_edf",
    candidates: Sequence[str] = ("np_dm", "precautious_dm", "lp"),
    task_scope: str | None = None,
    include_non_rt: bool = False,
    horizon: float | None = None,
    lp_objective: str = "response_time",
    lp_time_limit_seconds: float | None = 30.0,
    wcrt_max_iterations: int = 64,
    wcrt_epsilon: float = 1e-9,
    arrival_analysis_mode: str | None = None,
    arrival_envelope_min_intervals: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Benchmark schedulable-rate uplift using plan feasibility + WCRT feasibility."""

    loader = ConfigLoader()
    case_reports: list[dict[str, Any]] = []
    baseline_pass = 0
    best_pass = 0
    candidate_only_pass = 0
    baseline_pass_non_empty = 0
    best_pass_non_empty = 0
    candidate_only_pass_non_empty = 0
    empty_scope_case_count = 0
    resolved_scope = normalize_task_scope(task_scope, include_non_rt=include_non_rt)

    unique_candidates = [item.strip().lower() for item in candidates if item.strip()]

    for raw_path in config_paths:
        path = Path(raw_path)
        raw_spec = loader.load(str(path))
        spec = apply_planning_overrides(
            raw_spec,
            arrival_analysis_mode=arrival_analysis_mode,
            arrival_envelope_min_intervals=arrival_envelope_min_intervals,
        )
        problem = PlanningProblem.from_model_spec(
            spec,
            task_scope=resolved_scope,
            include_non_rt=include_non_rt,
            horizon=horizon,
        )
        is_empty_scope_case = len(problem.segments) == 0
        if is_empty_scope_case:
            empty_scope_case_count += 1

        baseline_eval = plan_and_analyze_schedulability(
            problem,
            planner=baseline,
            task_scope=resolved_scope,
            include_non_rt=include_non_rt,
            horizon=horizon,
            lp_objective=lp_objective,
            time_limit_seconds=lp_time_limit_seconds,
            max_iterations=wcrt_max_iterations,
            epsilon=wcrt_epsilon,
        )
        baseline_feasible = bool(baseline_eval["schedulable"])
        baseline_pass += int(baseline_feasible)
        if not is_empty_scope_case:
            baseline_pass_non_empty += int(baseline_feasible)

        candidate_results: dict[str, dict[str, bool]] = {}
        for candidate in unique_candidates:
            candidate_eval = plan_and_analyze_schedulability(
                problem,
                planner=candidate,
                task_scope=resolved_scope,
                include_non_rt=include_non_rt,
                horizon=horizon,
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

        best_candidate_feasible = baseline_feasible or any(
            item["schedulable"] for item in candidate_results.values()
        )
        candidate_only_feasible = any(item["schedulable"] for item in candidate_results.values())
        best_pass += int(best_candidate_feasible)
        candidate_only_pass += int(candidate_only_feasible)
        if not is_empty_scope_case:
            best_pass_non_empty += int(best_candidate_feasible)
            candidate_only_pass_non_empty += int(candidate_only_feasible)

        case_reports.append(
            {
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
            }
        )

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

    return {
        "total_cases": total,
        "empty_scope_case_count": empty_scope_case_count,
        "non_empty_case_count": non_empty_case_count,
        "baseline": baseline,
        "candidates": unique_candidates,
        "task_scope": resolved_scope,
        "wcrt_max_iterations": wcrt_max_iterations,
        "wcrt_epsilon": wcrt_epsilon,
        "arrival_analysis_mode": arrival_analysis_mode or "sample_path",
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


def csv_rows_for_os_windows(os_config: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    priorities = {
        str(item.get("task_id")): item.get("priority")
        for item in os_config.get("threads", [])
        if isinstance(item, Mapping)
    }
    for window in os_config.get("schedule_windows", []):
        if not isinstance(window, Mapping):
            continue
        task_id = str(window.get("task_id", ""))
        rows.append(
            {
                "task_id": task_id,
                "priority": priorities.get(task_id),
                "core_id": window.get("core_id"),
                "segment_key": window.get("segment_key"),
                "start_time": window.get("start_time"),
                "end_time": window.get("end_time"),
                "absolute_deadline": window.get("absolute_deadline"),
            }
        )
    return rows


def collect_config_paths(configs: Iterable[str], config_list_file: str | None = None) -> list[str]:
    paths = [item for item in configs if item]
    if config_list_file:
        list_path = Path(config_list_file)
        for line in list_path.read_text(encoding="utf-8").splitlines():
            normalized = line.strip()
            if not normalized or normalized.startswith("#"):
                continue
            paths.append(normalized)
    deduped: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        deduped.append(path)
    return deduped
