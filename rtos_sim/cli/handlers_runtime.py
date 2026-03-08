"""Runtime simulation CLI command handlers."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from rtos_sim import api as sim_api
from collections.abc import Callable

from rtos_sim.analysis import build_audit_report, build_model_relations_report
from rtos_sim.cli.handlers_planning import resolve_plan_match_strictness
from rtos_sim.cli.shared_helpers import (
    read_planning_result as _read_planning_result,
    validate_plan_fingerprint_match as _validate_plan_fingerprint_match,
    write_json as _write_json,
)
from rtos_sim.core import SimEngine
from rtos_sim.io import ConfigError, ConfigLoader


def _write_jsonl(path: str, rows: list[dict[str, Any]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as file_obj:
        for row in rows:
            file_obj.write(json.dumps(row, ensure_ascii=False) + "\n")


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
    with output.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
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


def _validate_run_args(args: argparse.Namespace) -> int | None:
    if args.step and args.delta is not None and args.delta <= 0:
        print("[ERROR] --delta must be > 0 when provided")
        return 1
    if args.pause_at is not None and args.pause_at < 0:
        print("[ERROR] --pause-at must be >= 0")
        return 1
    return None


def cmd_run(
    args: argparse.Namespace,
    *,
    build_audit_report_fn: Callable[..., dict[str, Any]] = build_audit_report,
    build_model_relations_report_fn: Callable[..., dict[str, Any]] = build_model_relations_report,
    read_planning_result_fn: Callable[[str], dict[str, Any]] = _read_planning_result,
    validate_plan_fingerprint_match_fn: Callable[..., bool] = _validate_plan_fingerprint_match,
    write_json_fn: Callable[[str, dict[str, Any]], None] = _write_json,
    sim_engine_cls: type[SimEngine] = SimEngine,
) -> int:
    loader = ConfigLoader()
    try:
        strict_plan_match = resolve_plan_match_strictness(args, command="run")
        if strict_plan_match is None:
            return 2
        spec = loader.load(args.config)
    except ConfigError as exc:
        print(f"[ERROR] {exc}")
        return 1

    if args.plan_json:
        try:
            plan_payload = read_planning_result_fn(args.plan_json)
        except ConfigError as exc:
            print(f"[ERROR] {exc}")
            return 1
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] failed to read plan-json: {exc}")
            return 1

        if not validate_plan_fingerprint_match_fn(
            command="run",
            spec=spec,
            plan_payload=plan_payload,
            strict=strict_plan_match,
        ):
            return 2
        try:
            spec = sim_api.materialize_runtime_spec_from_plan(spec, plan_payload)
        except (ConfigError, ValueError) as exc:
            print(f"[ERROR] run: failed to materialize plan-json into runtime static windows: {exc}")
            return 1

    validation_error = _validate_run_args(args)
    if validation_error is not None:
        return validation_error

    engine = sim_engine_cls()
    try:
        engine.build(spec)
        horizon = args.until if args.until is not None else spec.sim.duration
        stop_at = min(horizon, args.pause_at) if args.pause_at is not None else horizon

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
        write_json_fn(metrics_out, metrics)
        if args.events_csv_out:
            _write_events_csv(args.events_csv_out, events)
        if args.audit_out:
            relation_summary = build_model_relations_report_fn(spec).get("summary")
            audit_report = build_audit_report_fn(
                events,
                scheduler_name=spec.scheduler.name,
                model_relation_summary=relation_summary,
            )
            write_json_fn(args.audit_out, audit_report)
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
