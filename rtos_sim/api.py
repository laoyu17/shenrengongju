"""Public service API façades for offline planning, WCRT analysis and exports."""

from __future__ import annotations

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
)
from rtos_sim.planning.facade_services import (
    build_os_config as _build_os_config,
    decorate_wcrt_report,
    evaluate_benchmark_case,
    finalize_benchmark_report,
    run_static_planner as _run_static_planner_service,
    schedule_table_to_runtime_windows as _schedule_table_to_runtime_windows,
    serialize_planning_artifact as _serialize_planning_artifact,
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
    return _run_static_planner_service(
        problem,
        planner=planner,
        lp_objective=lp_objective,
        time_limit_seconds=time_limit_seconds,
    )


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

    return decorate_wcrt_report(
        report,
        problem=problem,
        normalized=normalized,
        task_scope=resolved_scope,
        include_non_rt=resolved_include_non_rt,
        horizon=resolved_horizon,
    )


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
    arrival_assumption_trace = payload.get("arrival_assumption_trace")
    if isinstance(arrival_assumption_trace, Mapping) and "arrival_assumption_trace" not in metadata:
        metadata["arrival_assumption_trace"] = dict(arrival_assumption_trace)
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
    return _serialize_planning_artifact(
        result,
        normalized,
        spec_fingerprint=spec_fingerprint,
        task_scope=resolved_scope,
        include_non_rt=resolved_include_non_rt,
        horizon=horizon,
        arrival_analysis_mode=arrival_analysis_mode,
        arrival_envelope_min_intervals=arrival_envelope_min_intervals,
    )


def export_os_config(
    schedule_table: ScheduleTable,
    *,
    policy: str = "deadline_then_wcet",
) -> dict[str, Any]:
    """Export thread priorities, core bindings and static windows."""
    return _build_os_config(schedule_table, policy=policy)


def schedule_table_to_runtime_windows(schedule_table: ScheduleTable) -> list[dict[str, Any]]:
    """Convert planning `ScheduleTable` windows to runtime static-window config rows."""
    return _schedule_table_to_runtime_windows(schedule_table)


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
        analyze_wcrt(
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
        case_eval = evaluate_benchmark_case(
            path,
            problem,
            baseline=baseline,
            candidates=unique_candidates,
            lp_objective=lp_objective,
            lp_time_limit_seconds=lp_time_limit_seconds,
            wcrt_max_iterations=wcrt_max_iterations,
            wcrt_epsilon=wcrt_epsilon,
        )
        case_reports.append(case_eval.case_report)
        baseline_pass += case_eval.baseline_pass
        best_pass += case_eval.best_pass
        candidate_only_pass += case_eval.candidate_only_pass
        baseline_pass_non_empty += case_eval.baseline_pass_non_empty
        best_pass_non_empty += case_eval.best_pass_non_empty
        candidate_only_pass_non_empty += case_eval.candidate_only_pass_non_empty
        empty_scope_case_count += case_eval.empty_scope_case_count

    return finalize_benchmark_report(
        case_reports=case_reports,
        baseline=baseline,
        candidates=unique_candidates,
        resolved_scope=resolved_scope,
        wcrt_max_iterations=wcrt_max_iterations,
        wcrt_epsilon=wcrt_epsilon,
        arrival_analysis_mode=arrival_analysis_mode,
        arrival_envelope_min_intervals=arrival_envelope_min_intervals,
        baseline_pass=baseline_pass,
        best_pass=best_pass,
        candidate_only_pass=candidate_only_pass,
        baseline_pass_non_empty=baseline_pass_non_empty,
        best_pass_non_empty=best_pass_non_empty,
        candidate_only_pass_non_empty=candidate_only_pass_non_empty,
        empty_scope_case_count=empty_scope_case_count,
    )


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
