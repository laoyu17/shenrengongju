"""Planning-related CLI command handlers."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from rtos_sim import api as sim_api
from rtos_sim.io import ConfigError, ConfigLoader
from rtos_sim.model import ModelSpec


def _write_json(path: str, payload: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_rows_csv(path: str, rows: list[dict[str, Any]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_json(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ConfigError(f"metrics file must be object: {path}")
    return payload


def _read_planning_result(path: str) -> dict[str, Any]:
    payload = _read_json(path)
    if not isinstance(payload.get("schedule_table"), dict):
        raise ConfigError(f"planning result missing schedule_table: {path}")
    return payload


def parse_arrival_envelope_min_intervals(raw: str | None) -> dict[str, float] | None:
    if raw is None or not str(raw).strip():
        return None
    result: dict[str, float] = {}
    for token in str(raw).split(","):
        item = token.strip()
        if not item:
            continue
        if "=" not in item:
            raise ConfigError(
                "arrival envelope min intervals must use 'task_id=value' comma-separated format"
            )
        task_id, value_raw = item.split("=", 1)
        task_id = task_id.strip()
        if not task_id:
            raise ConfigError("arrival envelope min intervals contain empty task id")
        try:
            value = float(value_raw)
        except ValueError as exc:
            raise ConfigError(f"arrival envelope min interval for '{task_id}' must be number") from exc
        if value <= 0:
            raise ConfigError(f"arrival envelope min interval for '{task_id}' must be > 0")
        result[task_id] = value
    return result or None


def apply_cli_planning_overrides(spec: ModelSpec, args: argparse.Namespace) -> ModelSpec:
    arrival_mode = args.arrival_analysis_mode if hasattr(args, "arrival_analysis_mode") else None
    arrival_envelope = parse_arrival_envelope_min_intervals(
        args.arrival_envelope_min_intervals if hasattr(args, "arrival_envelope_min_intervals") else None
    )
    return sim_api.apply_planning_overrides(
        spec,
        arrival_analysis_mode=arrival_mode,
        arrival_envelope_min_intervals=arrival_envelope,
    )


def _validate_plan_fingerprint_match(
    *,
    command: str,
    spec: ModelSpec,
    plan_payload: dict[str, Any],
    strict: bool,
) -> bool:
    expectations = sim_api.plan_fingerprint_expectations(spec, plan_payload)
    expected_spec = str(expectations["expected_spec_fingerprint"])
    actual_spec = expectations["actual_spec_fingerprint"]
    if not actual_spec:
        level = "[ERROR]" if strict else "[WARN]"
        print(f"{level} {command}: plan-json missing spec_fingerprint, 期望指纹#{expected_spec}")
        return not strict
    if actual_spec != expected_spec:
        level = "[ERROR]" if strict else "[WARN]"
        print(
            f"{level} {command}: plan/config mismatch, "
            f"期望指纹#{expected_spec}, 实际指纹#{actual_spec}"
        )
        return not strict

    expected_semantic = expectations["expected_semantic_fingerprint"]
    actual_semantic = expectations["actual_semantic_fingerprint"]
    if not isinstance(actual_semantic, str) or not actual_semantic.strip():
        level = "[ERROR]" if strict else "[WARN]"
        print(
            f"{level} {command}: plan-json missing semantic_fingerprint, "
            f"期望语义指纹#{expected_semantic}"
        )
        return not strict
    if actual_semantic != expected_semantic:
        level = "[ERROR]" if strict else "[WARN]"
        print(
            f"{level} {command}: plan semantic mismatch, "
            f"期望语义指纹#{expected_semantic}, 实际语义指纹#{actual_semantic}"
        )
        return not strict
    return True


def _resolve_planning_options(
    *,
    spec: ModelSpec,
    planner: str | None,
    lp_objective: str | None,
    task_scope: str | None,
    include_non_rt: bool,
    horizon: float | None,
) -> tuple[str, str, str, bool, float | None]:
    planning_cfg = spec.planning
    resolved_planner = planner or (
        planning_cfg.planner if planning_cfg is not None else sim_api.DEFAULT_PLANNING_SECTION["planner"]
    )
    resolved_objective = lp_objective or (
        planning_cfg.lp_objective
        if planning_cfg is not None
        else sim_api.DEFAULT_PLANNING_SECTION["lp_objective"]
    )
    resolved_task_scope = task_scope or (
        planning_cfg.task_scope
        if planning_cfg is not None
        else sim_api.DEFAULT_PLANNING_SECTION["task_scope"]
    )
    resolved_include_non_rt = include_non_rt or (
        bool(planning_cfg.include_non_rt) if planning_cfg is not None else False
    )
    resolved_horizon = horizon if horizon is not None else (
        planning_cfg.horizon if planning_cfg is not None else None
    )
    return (
        str(resolved_planner),
        str(resolved_objective),
        str(resolved_task_scope),
        bool(resolved_include_non_rt),
        resolved_horizon,
    )


def cmd_plan_static(args: argparse.Namespace) -> int:
    loader = ConfigLoader()
    try:
        raw_spec = loader.load(args.config)
        spec = apply_cli_planning_overrides(raw_spec, args)
        planner, lp_objective, task_scope, include_non_rt, horizon = _resolve_planning_options(
            spec=spec,
            planner=args.planner,
            lp_objective=args.lp_objective,
            task_scope=args.task_scope,
            include_non_rt=args.include_non_rt,
            horizon=args.horizon,
        )
        result = sim_api.plan_static(
            spec,
            planner=planner,
            task_scope=task_scope,
            include_non_rt=include_non_rt,
            horizon=horizon,
            lp_objective=lp_objective,
            time_limit_seconds=args.time_limit,
        )
    except ConfigError as exc:
        print(f"[ERROR] {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] unexpected plan-static error: {exc}")
        return 1

    out_json = args.out_json or "artifacts/plan_static.json"
    try:
        result_payload = sim_api.serialize_planning_result(
            result,
            spec_or_payload=spec,
            task_scope=task_scope,
            include_non_rt=include_non_rt,
            horizon=horizon,
        )
        spec_fingerprint = sim_api.model_spec_fingerprint(raw_spec)
        result_payload["spec_fingerprint"] = spec_fingerprint
        metadata = result_payload.get("metadata")
        if isinstance(metadata, dict):
            metadata["spec_fingerprint"] = spec_fingerprint
        _write_json(out_json, result_payload)
        if args.out_csv:
            rows = [window.to_dict() for window in result.schedule_table.windows]
            _write_rows_csv(args.out_csv, rows)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] failed to write plan-static outputs: {exc}")
        return 1

    print(
        "[OK] static planning completed, "
        f"planner={result.planner}, feasible={result.feasible}, "
        f"windows={len(result.schedule_table.windows)}, json={out_json}, csv={args.out_csv or '-'}"
    )
    if args.strict_on_infeasible and not result.feasible:
        print("[ERROR] static planning infeasible in strict mode")
        return 2
    return 0


def cmd_analyze_wcrt(args: argparse.Namespace) -> int:
    loader = ConfigLoader()
    try:
        raw_spec = loader.load(args.config)
        spec = apply_cli_planning_overrides(raw_spec, args)
        planner, lp_objective, task_scope, include_non_rt, horizon = _resolve_planning_options(
            spec=spec,
            planner=args.planner,
            lp_objective=args.lp_objective,
            task_scope=args.task_scope,
            include_non_rt=args.include_non_rt,
            horizon=args.horizon,
        )
        if args.plan_json:
            plan_payload = _read_planning_result(args.plan_json)
            if not _validate_plan_fingerprint_match(
                command="analyze-wcrt",
                spec=raw_spec,
                plan_payload=plan_payload,
                strict=args.strict_plan_match,
            ):
                return 2
            plan_context = sim_api.extract_plan_planning_context(plan_payload)
            spec = sim_api.apply_planning_overrides(
                raw_spec,
                arrival_analysis_mode=(
                    str(plan_context["arrival_analysis_mode"])
                    if isinstance(plan_context.get("arrival_analysis_mode"), str)
                    else None
                ),
                arrival_envelope_min_intervals=(
                    plan_context["arrival_envelope_min_intervals"]
                    if isinstance(plan_context.get("arrival_envelope_min_intervals"), dict)
                    else None
                ),
            )
            task_scope = str(plan_context["task_scope"])
            include_non_rt = bool(plan_context["include_non_rt"])
            horizon = plan_context["horizon"]
            schedule_table = sim_api.planning_result_from_dict(plan_payload).schedule_table
        else:
            schedule_table = sim_api.plan_static(
                spec,
                planner=planner,
                task_scope=task_scope,
                include_non_rt=include_non_rt,
                horizon=horizon,
                lp_objective=lp_objective,
                time_limit_seconds=args.time_limit,
            ).schedule_table
        report = sim_api.analyze_wcrt(
            spec,
            schedule_table,
            task_scope=task_scope,
            include_non_rt=include_non_rt,
            horizon=horizon,
            max_iterations=args.max_iterations,
            epsilon=args.epsilon,
        )
    except ConfigError as exc:
        print(f"[ERROR] {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] unexpected analyze-wcrt error: {exc}")
        return 1

    out_json = args.out_json or "artifacts/wcrt_report.json"
    try:
        _write_json(out_json, report.to_dict())
        if args.out_csv:
            rows = [item.to_dict() for item in report.items]
            _write_rows_csv(args.out_csv, rows)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] failed to write analyze-wcrt outputs: {exc}")
        return 1

    print(
        "[OK] wcrt analysis completed, "
        f"feasible={report.feasible}, tasks={len(report.items)}, "
        f"json={out_json}, csv={args.out_csv or '-'}"
    )
    if args.strict_on_fail and not report.feasible:
        print("[ERROR] WCRT result is not schedulable in strict mode")
        return 2
    return 0


def cmd_export_os_config(args: argparse.Namespace) -> int:
    try:
        if args.plan_json:
            plan_payload = _read_planning_result(args.plan_json)
            if args.config:
                loader = ConfigLoader()
                spec = loader.load(args.config)
                if not _validate_plan_fingerprint_match(
                    command="export-os-config",
                    spec=spec,
                    plan_payload=plan_payload,
                    strict=args.strict_plan_match,
                ):
                    return 2
            elif args.strict_plan_match:
                print("[ERROR] export-os-config: --strict-plan-match requires --config with --plan-json")
                return 2
            schedule_table = sim_api.planning_result_from_dict(plan_payload).schedule_table
        elif args.config:
            loader = ConfigLoader()
            raw_spec = loader.load(args.config)
            spec = apply_cli_planning_overrides(raw_spec, args)
            planner, lp_objective, task_scope, include_non_rt, horizon = _resolve_planning_options(
                spec=spec,
                planner=args.planner,
                lp_objective=args.lp_objective,
                task_scope=args.task_scope,
                include_non_rt=args.include_non_rt,
                horizon=args.horizon,
            )
            schedule_table = sim_api.plan_static(
                spec,
                planner=planner,
                task_scope=task_scope,
                include_non_rt=include_non_rt,
                horizon=horizon,
                lp_objective=lp_objective,
                time_limit_seconds=args.time_limit,
            ).schedule_table
        else:
            print("[ERROR] export-os-config requires --plan-json or --config")
            return 1

        os_payload = sim_api.export_os_config(schedule_table, policy=args.policy)
    except ConfigError as exc:
        print(f"[ERROR] {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] unexpected export-os-config error: {exc}")
        return 1

    out_json = args.out_json or "artifacts/os_config.json"
    try:
        _write_json(out_json, os_payload)
        if args.out_csv:
            _write_rows_csv(args.out_csv, sim_api.csv_rows_for_os_windows(os_payload))
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] failed to write export-os-config outputs: {exc}")
        return 1

    print(
        "[OK] os config exported, "
        f"threads={len(os_payload.get('threads', []))}, windows={len(os_payload.get('schedule_windows', []))}, "
        f"json={out_json}, csv={args.out_csv or '-'}"
    )
    return 0
