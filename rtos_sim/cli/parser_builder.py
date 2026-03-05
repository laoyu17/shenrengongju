"""Argument parser builder with explicit command-handler wiring."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping


CommandHandler = Callable[[argparse.Namespace], int]


def _handler(command_handlers: Mapping[str, CommandHandler], name: str) -> CommandHandler:
    handler = command_handlers.get(name)
    if handler is None:
        raise KeyError(f"missing command handler: {name}")
    return handler


def build_parser(command_handlers: Mapping[str, CommandHandler]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rtos-sim", description="RTOS simulation CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="validate config file")
    validate_parser.add_argument("-c", "--config", required=True, help="path to config YAML/JSON")
    validate_parser.add_argument(
        "--strict-id-tokens",
        action="store_true",
        help="fail when IDs include reserved delimiters used by internal composite keys",
    )
    validate_parser.set_defaults(func=_handler(command_handlers, "validate"))

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
    run_parser.set_defaults(func=_handler(command_handlers, "run"))

    ui_parser = subparsers.add_parser("ui", help="launch PyQt UI")
    ui_parser.add_argument("-c", "--config", default=None, help="path to initial config")
    ui_parser.set_defaults(func=_handler(command_handlers, "ui"))

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
    batch_parser.set_defaults(func=_handler(command_handlers, "batch-run"))

    compare_parser = subparsers.add_parser("compare", help="compare two metrics json files")
    compare_parser.add_argument("--left-metrics", required=True, help="left metrics JSON path")
    compare_parser.add_argument("--right-metrics", required=True, help="right metrics JSON path")
    compare_parser.add_argument("--left-label", default="left", help="left side label")
    compare_parser.add_argument("--right-label", default="right", help="right side label")
    compare_parser.add_argument("--out-json", default=None, help="compare report JSON path")
    compare_parser.add_argument("--out-csv", default=None, help="compare rows CSV path")
    compare_parser.set_defaults(func=_handler(command_handlers, "compare"))

    inspect_parser = subparsers.add_parser("inspect-model", help="export model relation tables")
    inspect_parser.add_argument("-c", "--config", required=True, help="path to config YAML/JSON")
    inspect_parser.add_argument("--out-json", default=None, help="relation report JSON path")
    inspect_parser.add_argument("--out-csv", default=None, help="relation report CSV path")
    inspect_parser.add_argument(
        "--strict-on-fail",
        action="store_true",
        help="return non-zero when model relation status is not pass",
    )
    inspect_parser.set_defaults(func=_handler(command_handlers, "inspect-model"))

    migrate_parser = subparsers.add_parser(
        "migrate-config",
        help="normalize version and remove deprecated scheduler params",
    )
    migrate_parser.add_argument("--in", dest="input_config", required=True, help="input config YAML/JSON")
    migrate_parser.add_argument("--out", dest="output_config", required=True, help="output config YAML/JSON")
    migrate_parser.add_argument("--report-out", default=None, help="optional migration report JSON path")
    migrate_parser.add_argument(
        "--no-validate",
        action="store_true",
        help="skip strict schema/model validation after migration",
    )
    migrate_parser.set_defaults(func=_handler(command_handlers, "migrate-config"))

    plan_static_parser = subparsers.add_parser(
        "plan-static",
        help="offline static planning with heuristic or LP planner",
    )
    plan_static_parser.add_argument("-c", "--config", required=True, help="path to config YAML/JSON")
    plan_static_parser.add_argument(
        "--planner",
        default=None,
        help="planner name: np_edf|np_dm|precautious_dm|lp (default from planning section)",
    )
    plan_static_parser.add_argument(
        "--lp-objective",
        default=None,
        help="LP objective when planner=lp: response_time|spread_execution",
    )
    plan_static_parser.add_argument(
        "--task-scope",
        default=None,
        help="planning task scope: sync_only|sync_and_dynamic_rt|all",
    )
    plan_static_parser.add_argument("--include-non-rt", action="store_true", help="include non_rt tasks")
    plan_static_parser.add_argument("--horizon", type=float, default=None, help="optional planning horizon")
    plan_static_parser.add_argument(
        "--time-limit",
        type=float,
        default=30.0,
        help="LP solver time limit in seconds",
    )
    plan_static_parser.add_argument("--out-json", default=None, help="planning result JSON path")
    plan_static_parser.add_argument("--out-csv", default=None, help="schedule windows CSV path")
    plan_static_parser.add_argument(
        "--strict-on-infeasible",
        action="store_true",
        help="return non-zero when planning result is infeasible",
    )
    plan_static_parser.set_defaults(func=_handler(command_handlers, "plan-static"))

    wcrt_parser = subparsers.add_parser(
        "analyze-wcrt",
        help="run analytical WCRT/RTA over static schedule table",
    )
    wcrt_parser.add_argument("-c", "--config", required=True, help="path to config YAML/JSON")
    wcrt_parser.add_argument("--plan-json", default=None, help="existing plan-static result JSON path")
    wcrt_parser.add_argument(
        "--strict-plan-match",
        action="store_true",
        help="strictly require --plan-json spec_fingerprint matches --config",
    )
    wcrt_parser.add_argument("--planner", default=None, help="planner used when --plan-json not provided")
    wcrt_parser.add_argument("--lp-objective", default=None, help="LP objective when planner=lp")
    wcrt_parser.add_argument(
        "--task-scope",
        default=None,
        help="planning task scope: sync_only|sync_and_dynamic_rt|all",
    )
    wcrt_parser.add_argument("--include-non-rt", action="store_true", help="include non_rt tasks")
    wcrt_parser.add_argument("--horizon", type=float, default=None, help="optional planning horizon")
    wcrt_parser.add_argument(
        "--time-limit",
        type=float,
        default=30.0,
        help="LP solver time limit in seconds when generating plan",
    )
    wcrt_parser.add_argument("--max-iterations", type=int, default=64, help="max fixed-point iterations")
    wcrt_parser.add_argument("--epsilon", type=float, default=1e-9, help="fixed-point convergence epsilon")
    wcrt_parser.add_argument("--out-json", default=None, help="WCRT report JSON path")
    wcrt_parser.add_argument("--out-csv", default=None, help="WCRT rows CSV path")
    wcrt_parser.add_argument(
        "--strict-on-fail",
        action="store_true",
        help="return non-zero when WCRT report is not fully schedulable",
    )
    wcrt_parser.set_defaults(func=_handler(command_handlers, "analyze-wcrt"))

    benchmark_parser = subparsers.add_parser(
        "benchmark-sched-rate",
        help="benchmark schedulable-rate uplift against baseline planner",
    )
    benchmark_parser.add_argument(
        "-c",
        "--configs",
        nargs="*",
        default=[],
        help="config paths to benchmark",
    )
    benchmark_parser.add_argument(
        "--config-list",
        default=None,
        help="optional text file containing config paths (one per line)",
    )
    benchmark_parser.add_argument("--baseline", default="np_edf", help="baseline planner")
    benchmark_parser.add_argument(
        "--candidates",
        default="np_dm,precautious_dm,lp",
        help="comma-separated candidate planners",
    )
    benchmark_parser.add_argument("--include-non-rt", action="store_true", help="include non_rt tasks")
    benchmark_parser.add_argument(
        "--task-scope",
        default=None,
        help="planning task scope: sync_only|sync_and_dynamic_rt|all",
    )
    benchmark_parser.add_argument("--horizon", type=float, default=None, help="optional planning horizon")
    benchmark_parser.add_argument(
        "--lp-objective",
        default="response_time",
        help="LP objective for lp candidate: response_time|spread_execution",
    )
    benchmark_parser.add_argument(
        "--lp-time-limit",
        type=float,
        default=30.0,
        help="LP solver time limit in seconds",
    )
    benchmark_parser.add_argument(
        "--wcrt-max-iterations",
        type=int,
        default=64,
        help="max fixed-point iterations for benchmark WCRT gating",
    )
    benchmark_parser.add_argument(
        "--wcrt-epsilon",
        type=float,
        default=1e-9,
        help="fixed-point epsilon for benchmark WCRT gating",
    )
    benchmark_parser.add_argument(
        "--target-uplift",
        type=float,
        default=None,
        help="optional strict gate: require uplift >= target",
    )
    benchmark_parser.add_argument("--out-json", default=None, help="benchmark report JSON path")
    benchmark_parser.add_argument("--out-csv", default=None, help="benchmark rows CSV path")
    benchmark_parser.set_defaults(func=_handler(command_handlers, "benchmark-sched-rate"))

    export_parser = subparsers.add_parser(
        "export-os-config",
        help="export OS-level thread/core/window configuration",
    )
    export_parser.add_argument("--plan-json", default=None, help="existing plan-static result JSON path")
    export_parser.add_argument("-c", "--config", default=None, help="path to config YAML/JSON")
    export_parser.add_argument(
        "--strict-plan-match",
        action="store_true",
        help="strictly require --plan-json spec_fingerprint matches --config",
    )
    export_parser.add_argument("--planner", default=None, help="planner used when --plan-json not provided")
    export_parser.add_argument("--lp-objective", default=None, help="LP objective when planner=lp")
    export_parser.add_argument(
        "--task-scope",
        default=None,
        help="planning task scope: sync_only|sync_and_dynamic_rt|all",
    )
    export_parser.add_argument("--include-non-rt", action="store_true", help="include non_rt tasks")
    export_parser.add_argument("--horizon", type=float, default=None, help="optional planning horizon")
    export_parser.add_argument(
        "--time-limit",
        type=float,
        default=30.0,
        help="LP solver time limit in seconds when generating plan",
    )
    export_parser.add_argument(
        "--policy",
        default="deadline_then_wcet",
        help="priority policy for thread config export",
    )
    export_parser.add_argument("--out-json", default=None, help="OS config JSON path")
    export_parser.add_argument("--out-csv", default=None, help="OS windows CSV path")
    export_parser.set_defaults(func=_handler(command_handlers, "export-os-config"))

    return parser
