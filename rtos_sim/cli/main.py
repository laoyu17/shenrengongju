"""CLI entrypoint for simulation and validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

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


def cmd_validate(args: argparse.Namespace) -> int:
    loader = ConfigLoader()
    issues = loader.validate(args.config)
    if issues:
        for issue in issues:
            print(f"[ERROR] {issue.path}: {issue.message}")
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

    engine = SimEngine()
    engine.build(spec)
    engine.run(until=args.until)

    events = [event.model_dump(mode="json") for event in engine.events]
    metrics = engine.metric_report()

    events_out = args.events_out or "artifacts/events.jsonl"
    metrics_out = args.metrics_out or "artifacts/metrics.json"
    _write_jsonl(events_out, events)
    _write_json(metrics_out, metrics)

    print(f"[OK] simulation completed, events={len(events)}, metrics={metrics_out}")
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
    run_parser.add_argument("--metrics-out", default=None, help="path to write metric JSON")
    run_parser.set_defaults(func=cmd_run)

    ui_parser = subparsers.add_parser("ui", help="launch PyQt UI")
    ui_parser.add_argument("-c", "--config", default=None, help="path to initial config")
    ui_parser.set_defaults(func=cmd_ui)

    batch_parser = subparsers.add_parser("batch-run", help="run matrix experiments")
    batch_parser.add_argument("-b", "--batch-config", required=True, help="path to batch config YAML/JSON")
    batch_parser.add_argument("--output-dir", default=None, help="batch output directory")
    batch_parser.add_argument("--summary-csv", default=None, help="summary CSV output path")
    batch_parser.add_argument("--summary-json", default=None, help="summary JSON output path")
    batch_parser.set_defaults(func=cmd_batch_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
