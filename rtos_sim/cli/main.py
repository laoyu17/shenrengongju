"""CLI entrypoint for simulation and validation."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import yaml

from rtos_sim import api as sim_api
from rtos_sim.analysis import (
    build_audit_report,
    build_compare_report,
    build_model_relations_report,
    compare_report_to_rows,
    model_relations_report_to_rows,
)
from rtos_sim.cli.handlers_planning import (
    cmd_analyze_wcrt,
    cmd_export_os_config,
    cmd_plan_static,
)
from rtos_sim.core import SimEngine
from rtos_sim.io import ConfigError, ConfigLoader, ExperimentRunner
from rtos_sim.model import ModelSpec
from rtos_sim.cli.parser_builder import build_parser as build_cli_parser


def _collect_id_token_warnings(spec: ModelSpec) -> list[str]:
    """Report identifiers that may conflict with composite key delimiters."""

    warnings: list[str] = []

    for index, processor in enumerate(spec.platform.processor_types):
        if ":" in processor.id:
            warnings.append(
                f"platform.processor_types[{index}].id='{processor.id}' contains ':'"
            )

    for index, core in enumerate(spec.platform.cores):
        if ":" in core.id:
            warnings.append(f"platform.cores[{index}].id='{core.id}' contains ':'")

    for index, resource in enumerate(spec.resources):
        if ":" in resource.id:
            warnings.append(f"resources[{index}].id='{resource.id}' contains ':'")

    for task_index, task in enumerate(spec.tasks):
        if ":" in task.id:
            warnings.append(f"tasks[{task_index}].id='{task.id}' contains ':'")
        if "@" in task.id:
            warnings.append(
                f"tasks[{task_index}].id='{task.id}' contains '@' (job_id uses task_id@release_index)"
            )
        for subtask_index, subtask in enumerate(task.subtasks):
            if ":" in subtask.id:
                warnings.append(
                    f"tasks[{task_index}].subtasks[{subtask_index}].id='{subtask.id}' contains ':'"
                )
            for segment_index, segment in enumerate(subtask.segments):
                if ":" in segment.id:
                    warnings.append(
                        "tasks"
                        f"[{task_index}].subtasks[{subtask_index}].segments[{segment_index}]"
                        f".id='{segment.id}' contains ':'"
                    )

    return warnings


def _write_jsonl(path: str, rows: list[dict[str, Any]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_json(path: str, payload: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_events_csv(path: str, rows: list[dict[str, Any]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "event_id",
        "seq",
        "correlation_id",
        "time",
        "type",
        "job_id",
        "segment_id",
        "core_id",
        "resource_id",
        "payload",
    ]
    with output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "event_id": row.get("event_id"),
                    "seq": row.get("seq"),
                    "correlation_id": row.get("correlation_id"),
                    "time": row.get("time"),
                    "type": row.get("type"),
                    "job_id": row.get("job_id"),
                    "segment_id": row.get("segment_id"),
                    "core_id": row.get("core_id"),
                    "resource_id": row.get("resource_id"),
                    "payload": json.dumps(row.get("payload", {}), ensure_ascii=False),
                }
            )


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


def _read_config_payload(path: str) -> dict[str, Any]:
    input_path = Path(path)
    if not input_path.exists():
        raise ConfigError(f"config file not found: {path}")
    text = input_path.read_text(encoding="utf-8")
    try:
        if input_path.suffix.lower() in {".yaml", ".yml"}:
            payload = yaml.safe_load(text)
        else:
            payload = json.loads(text)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise ConfigError(f"invalid config syntax: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConfigError("config root must be object")
    return payload


def _looks_like_batch_payload(payload: dict[str, Any]) -> bool:
    has_batch_fields = isinstance(payload.get("base_config"), str) and isinstance(payload.get("factors"), dict)
    has_runtime_fields = {"platform", "tasks", "scheduler", "sim"}.issubset(payload.keys())
    return has_batch_fields and not has_runtime_fields


def _write_config_payload(path: str, payload: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() in {".yaml", ".yml"}:
        output_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    else:
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_validate(args: argparse.Namespace) -> int:
    loader = ConfigLoader()
    payload: dict[str, Any] | None = None
    try:
        payload = _read_config_payload(args.config)
        spec = loader.load_data(payload)
        # Build-time plugin resolution must pass during validate.
        SimEngine().build(spec)
    except ConfigError as exc:
        print(f"[ERROR] {args.config}: {exc}")
        if payload is not None and _looks_like_batch_payload(payload):
            print("[HINT] batch matrix detected, use `rtos-sim batch-run -b <file>`")
        return 1
    except ValueError as exc:
        print(f"[ERROR] {args.config}: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI should not leak traceback by default.
        print(f"[ERROR] {args.config}: unexpected validation error: {exc}")
        return 1
    id_token_warnings = _collect_id_token_warnings(spec)
    if id_token_warnings:
        for warning in id_token_warnings:
            print(f"[WARN] id-token-safety: {warning}")
        if args.strict_id_tokens:
            print("[ERROR] id token safety check failed in strict mode")
            return 2
    print("[OK] config validation passed")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    loader = ConfigLoader()
    try:
        spec = loader.load(args.config)
    except ConfigError as exc:
        print(f"[ERROR] {exc}")
        return 1

    if args.step and args.delta is not None and args.delta <= 0:
        print("[ERROR] --delta must be > 0 when provided")
        return 1
    if args.pause_at is not None and args.pause_at < 0:
        print("[ERROR] --pause-at must be >= 0")
        return 1

    engine = SimEngine()
    try:
        engine.build(spec)
        horizon = args.until if args.until is not None else spec.sim.duration
        stop_at = horizon
        if args.pause_at is not None:
            stop_at = min(stop_at, args.pause_at)

        if args.step:
            step_delta = args.delta
            while engine.now < stop_at - 1e-12:
                before = engine.now
                if step_delta is None:
                    engine.step()
                else:
                    engine.step(step_delta)
                if engine.now <= before + 1e-12:
                    break
            engine.run(until=stop_at)
        else:
            engine.run(until=stop_at)

        if args.pause_at is not None and stop_at < horizon - 1e-12:
            engine.pause()

        events = [event.model_dump(mode="json") for event in engine.events]
        metrics = engine.metric_report()

        events_out = args.events_out or "artifacts/events.jsonl"
        metrics_out = args.metrics_out or "artifacts/metrics.json"
        _write_jsonl(events_out, events)
        _write_json(metrics_out, metrics)
        if args.events_csv_out:
            _write_events_csv(args.events_csv_out, events)
        if args.audit_out:
            relation_summary = build_model_relations_report(spec).get("summary")
            audit_report = build_audit_report(
                events,
                scheduler_name=spec.scheduler.name,
                model_relation_summary=relation_summary,
            )
            _write_json(args.audit_out, audit_report)
            if audit_report["status"] != "pass":
                print(f"[ERROR] simulation audit failed, report={args.audit_out}")
                return 2
    except ValueError as exc:
        print(f"[ERROR] {exc}")
        return 1
    except RuntimeError as exc:
        print(f"[ERROR] simulation runtime error: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI should provide stable non-zero exit.
        print(f"[ERROR] unexpected simulation error: {exc}")
        return 1

    print(
        f"[OK] simulation completed, events={len(events)}, now={engine.now:.3f}, "
        f"metrics={metrics_out}"
    )
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    try:
        from rtos_sim.ui.app import run_ui
    except ImportError as exc:  # pragma: no cover - environment dependent
        print(f"[ERROR] UI dependencies missing: {exc}")
        return 1
    try:
        run_ui(config_path=args.config)
    except Exception as exc:  # noqa: BLE001 - UI errors should still return non-zero cleanly.
        print(f"[ERROR] UI launch failed: {exc}")
        return 1
    return 0


def cmd_batch_run(args: argparse.Namespace) -> int:
    runner = ExperimentRunner()
    try:
        summary = runner.run_batch(
            args.batch_config,
            output_dir=args.output_dir,
            summary_csv=args.summary_csv,
            summary_json=args.summary_json,
        )
    except ConfigError as exc:
        print(f"[ERROR] {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] unexpected batch-run error: {exc}")
        return 1

    print(
        "[OK] batch simulation completed, "
        f"runs={summary.total_runs}, success={summary.succeeded_runs}, failed={summary.failed_runs}, "
        f"csv={summary.summary_csv}, json={summary.summary_json}"
    )
    if args.strict_fail_on_error and summary.failed_runs > 0:
        print("[ERROR] batch simulation contains failed runs in strict mode")
        return 2
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    try:
        left_metrics = _read_json(args.left_metrics)
        right_metrics = _read_json(args.right_metrics)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}")
        return 1

    report = build_compare_report(
        left_metrics,
        right_metrics,
        left_label=args.left_label or "left",
        right_label=args.right_label or "right",
    )
    if args.out_json:
        _write_json(args.out_json, report)
    if args.out_csv:
        _write_rows_csv(args.out_csv, compare_report_to_rows(report))

    print(
        "[OK] metrics compare completed, "
        f"left={args.left_metrics}, right={args.right_metrics}, "
        f"json={args.out_json or '-'}, csv={args.out_csv or '-'}"
    )
    return 0


def cmd_inspect_model(args: argparse.Namespace) -> int:
    loader = ConfigLoader()
    try:
        spec = loader.load(args.config)
    except ConfigError as exc:
        print(f"[ERROR] {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] unexpected inspect-model error: {exc}")
        return 1

    try:
        report = build_model_relations_report(spec)
        out_json = args.out_json or "artifacts/model_relations.json"
        _write_json(out_json, report)
        if args.out_csv:
            _write_rows_csv(args.out_csv, model_relations_report_to_rows(report))
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] unexpected inspect-model error: {exc}")
        return 1

    csv_path = args.out_csv if args.out_csv else "-"
    report_status = str(report.get("status") or "unknown")
    if args.strict_on_fail and report_status != "pass":
        print(
            "[ERROR] model relation report status is not pass in strict mode, "
            f"status={report_status}, config={args.config}, json={out_json}, csv={csv_path}"
        )
        return 2
    print(
        "[OK] model relation report completed, "
        f"config={args.config}, json={out_json}, csv={csv_path}, status={report_status}"
    )
    return 0


def cmd_migrate_config(args: argparse.Namespace) -> int:
    loader = ConfigLoader()
    try:
        source = _read_config_payload(args.input_config)
        migrated, report = loader.migrate_data(source)
        if not args.no_validate:
            loader.load_data(migrated)
    except ConfigError as exc:
        print(f"[ERROR] {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] unexpected migrate-config error: {exc}")
        return 1

    try:
        _write_config_payload(args.output_config, migrated)
        if args.report_out:
            _write_json(args.report_out, report)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] failed to write migrate-config outputs: {exc}")
        return 1

    print(
        "[OK] config migration completed, "
        f"in={args.input_config}, out={args.output_config}, "
        f"removed_keys={len(report['removed_keys'])}, "
        f"added_keys={len(report.get('added_keys', []))}, "
        f"validated={'no' if args.no_validate else 'yes'}"
    )
    return 0


def _benchmark_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in report.get("cases", []):
        if not isinstance(case, dict):
            continue
        base = {
            "config": case.get("config"),
            "baseline": case.get("baseline"),
            "baseline_planning_feasible": case.get("baseline_planning_feasible"),
            "baseline_wcrt_feasible": case.get("baseline_wcrt_feasible"),
            "baseline_feasible": case.get("baseline_feasible"),
            "best_candidate_feasible": case.get("best_candidate_feasible"),
            "candidate_only_feasible": case.get("candidate_only_feasible"),
        }
        candidates = case.get("candidates", {})
        if isinstance(candidates, dict):
            for planner, feasible in sorted(candidates.items()):
                if isinstance(feasible, dict):
                    rows.append(
                        {
                            **base,
                            "planner": planner,
                            "planning_feasible": feasible.get("planning_feasible"),
                            "wcrt_feasible": feasible.get("wcrt_feasible"),
                            "feasible": feasible.get("schedulable"),
                        }
                    )
                else:
                    rows.append({**base, "planner": planner, "feasible": feasible})
        else:
            rows.append({**base, "planner": "", "feasible": None})
    return rows


def cmd_benchmark_sched_rate(args: argparse.Namespace) -> int:
    try:
        config_paths = sim_api.collect_config_paths(args.configs or [], args.config_list)
        if not config_paths:
            print("[ERROR] benchmark-sched-rate requires at least one config path")
            return 1
        candidates = [item.strip() for item in args.candidates.split(",") if item.strip()]
        report = sim_api.benchmark_sched_rate(
            config_paths,
            baseline=args.baseline,
            candidates=candidates,
            task_scope=args.task_scope,
            include_non_rt=args.include_non_rt,
            horizon=args.horizon,
            lp_objective=args.lp_objective,
            lp_time_limit_seconds=args.lp_time_limit,
            wcrt_max_iterations=args.wcrt_max_iterations,
            wcrt_epsilon=args.wcrt_epsilon,
        )
    except ConfigError as exc:
        print(f"[ERROR] {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] unexpected benchmark-sched-rate error: {exc}")
        return 1

    out_json = args.out_json or "artifacts/benchmark_sched_rate.json"
    try:
        _write_json(out_json, report)
        if args.out_csv:
            _write_rows_csv(args.out_csv, _benchmark_rows(report))
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] failed to write benchmark-sched-rate outputs: {exc}")
        return 1

    print(
        "[OK] sched-rate benchmark completed, "
        f"cases={report.get('total_cases', 0)}, baseline_rate={report.get('baseline_schedulable_rate')}, "
        f"candidate_rate={report.get('best_candidate_schedulable_rate')}, "
        f"candidate_only_rate={report.get('candidate_only_schedulable_rate')}, "
        f"non_empty_cases={report.get('non_empty_case_count')}, "
        f"uplift={report.get('uplift')}, candidate_only_uplift={report.get('candidate_only_uplift')}, "
        f"json={out_json}, csv={args.out_csv or '-'}"
    )

    strict_uplift = float(report.get("candidate_only_uplift", report.get("uplift", 0.0)))
    if args.target_uplift is not None and strict_uplift < args.target_uplift:
        print(
            "[ERROR] uplift target not met, "
            f"target={args.target_uplift}, actual={strict_uplift} (metric=candidate_only_uplift)"
        )
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    return build_cli_parser(
        {
            "validate": cmd_validate,
            "run": cmd_run,
            "ui": cmd_ui,
            "batch-run": cmd_batch_run,
            "compare": cmd_compare,
            "inspect-model": cmd_inspect_model,
            "migrate-config": cmd_migrate_config,
            "plan-static": cmd_plan_static,
            "analyze-wcrt": cmd_analyze_wcrt,
            "benchmark-sched-rate": cmd_benchmark_sched_rate,
            "export-os-config": cmd_export_os_config,
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
