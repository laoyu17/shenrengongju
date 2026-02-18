"""CLI entrypoint for simulation and validation."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from rtos_sim.analysis import build_audit_report, build_compare_report, compare_report_to_rows
from rtos_sim.core import SimEngine
from rtos_sim.io import ConfigError, ConfigLoader, ExperimentRunner


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


def cmd_validate(args: argparse.Namespace) -> int:
    loader = ConfigLoader()
    try:
        spec = loader.load(args.config)
    except ConfigError as exc:
        print(f"[ERROR] {args.config}: {exc}")
        return 1
    try:
        # Build-time plugin resolution must pass during validate.
        SimEngine().build(spec)
    except ValueError as exc:
        print(f"[ERROR] {args.config}: {exc}")
        return 1
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
        audit_report = build_audit_report(events, scheduler_name=spec.scheduler.name)
        _write_json(args.audit_out, audit_report)
        if audit_report["status"] != "pass":
            print(f"[ERROR] simulation audit failed, report={args.audit_out}")
            return 2

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
    run_ui(config_path=args.config)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rtos-sim", description="RTOS simulation CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="validate config file")
    validate_parser.add_argument("-c", "--config", required=True, help="path to config YAML/JSON")
    validate_parser.set_defaults(func=cmd_validate)

    run_parser = subparsers.add_parser("run", help="run simulation")
    run_parser.add_argument("-c", "--config", required=True, help="path to config YAML/JSON")
    run_parser.add_argument("--until", type=float, default=None, help="override simulation duration")
    run_parser.add_argument("--events-out", default=None, help="path to write JSONL events")
    run_parser.add_argument("--events-csv-out", default=None, help="path to write CSV events")
    run_parser.add_argument("--metrics-out", default=None, help="path to write metric JSON")
    run_parser.add_argument("--audit-out", default=None, help="path to write audit report JSON")
    run_parser.add_argument("--step", action="store_true", help="execute simulation by step loop")
    run_parser.add_argument("--delta", type=float, default=None, help="delta for --step mode")
    run_parser.add_argument(
        "--pause-at",
        type=float,
        default=None,
        help="stop advancing at this simulation time and keep partial results",
    )
    run_parser.set_defaults(func=cmd_run)

    ui_parser = subparsers.add_parser("ui", help="launch PyQt UI")
    ui_parser.add_argument("-c", "--config", default=None, help="path to initial config")
    ui_parser.set_defaults(func=cmd_ui)

    batch_parser = subparsers.add_parser("batch-run", help="run matrix experiments")
    batch_parser.add_argument("-b", "--batch-config", required=True, help="path to batch config YAML/JSON")
    batch_parser.add_argument("--output-dir", default=None, help="batch output directory")
    batch_parser.add_argument("--summary-csv", default=None, help="summary CSV output path")
    batch_parser.add_argument("--summary-json", default=None, help="summary JSON output path")
    batch_parser.add_argument(
        "--strict-fail-on-error",
        action="store_true",
        help="return non-zero when any batch run fails",
    )
    batch_parser.set_defaults(func=cmd_batch_run)

    compare_parser = subparsers.add_parser("compare", help="compare two metrics json files")
    compare_parser.add_argument("--left-metrics", required=True, help="left metrics JSON path")
    compare_parser.add_argument("--right-metrics", required=True, help="right metrics JSON path")
    compare_parser.add_argument("--left-label", default="left", help="left side label")
    compare_parser.add_argument("--right-label", default="right", help="right side label")
    compare_parser.add_argument("--out-json", default=None, help="compare report JSON path")
    compare_parser.add_argument("--out-csv", default=None, help="compare rows CSV path")
    compare_parser.set_defaults(func=cmd_compare)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
