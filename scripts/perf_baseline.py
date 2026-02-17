"""Baseline performance gate for medium-sized simulation scenarios."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from rtos_sim.core import SimEngine
from rtos_sim.io import ConfigLoader


def _parse_int_list(raw: str) -> list[int]:
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def _parse_float_list(raw: str | None) -> list[float]:
    if raw is None or not raw.strip():
        return []
    return [float(item.strip()) for item in raw.split(",") if item.strip()]


def _build_payload(task_count: int, seed: int) -> dict:
    core_ids = ["c0", "c1", "c2", "c3"]
    tasks: list[dict] = []
    for idx in range(task_count):
        core_id = core_ids[idx % len(core_ids)]
        wcet = 0.6 + (idx % 3) * 0.2
        deadline = 20 + (idx % 7)
        arrival = (idx % 50) * 0.05
        tasks.append(
            {
                "id": f"t{idx:03d}",
                "name": f"task-{idx:03d}",
                "task_type": "dynamic_rt",
                "deadline": deadline,
                "arrival": arrival,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [
                            {
                                "id": "seg0",
                                "index": 1,
                                "wcet": wcet,
                                "mapping_hint": core_id,
                            }
                        ],
                    }
                ],
            }
        )

    return {
        "version": "0.2",
        "platform": {
            "processor_types": [
                {"id": "CPU", "name": "cpu", "core_count": 4, "speed_factor": 1.0},
            ],
            "cores": [
                {"id": "c0", "type_id": "CPU", "speed_factor": 1.0},
                {"id": "c1", "type_id": "CPU", "speed_factor": 1.0},
                {"id": "c2", "type_id": "CPU", "speed_factor": 1.0},
                {"id": "c3", "type_id": "CPU", "speed_factor": 1.0},
            ],
        },
        "resources": [],
        "tasks": tasks,
        "scheduler": {
            "name": "edf",
            "params": {
                "event_id_mode": "deterministic",
            },
        },
        "sim": {"duration": 60, "seed": seed},
    }


def _run_case(task_count: int, seed: int) -> dict:
    payload = _build_payload(task_count, seed)
    spec = ConfigLoader().load_data(payload)
    engine = SimEngine()
    started = time.perf_counter()
    engine.build(spec)
    engine.run()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    metrics = engine.metric_report()
    return {
        "task_count": task_count,
        "wall_time_ms": elapsed_ms,
        "jobs_released": metrics.get("jobs_released", 0),
        "jobs_completed": metrics.get("jobs_completed", 0),
        "event_count": metrics.get("event_count", 0),
        "max_time": metrics.get("max_time", 0.0),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run baseline perf checks for medium scenarios")
    parser.add_argument(
        "--tasks",
        default="100,300",
        help="comma-separated task counts to run, e.g. 100,300",
    )
    parser.add_argument(
        "--max-wall-ms",
        default="",
        help="comma-separated wall-time thresholds, aligned with --tasks",
    )
    parser.add_argument("--seed", type=int, default=7, help="simulation seed")
    parser.add_argument(
        "--output",
        default="artifacts/perf/perf-baseline.json",
        help="where to write json report",
    )
    args = parser.parse_args(argv)

    task_counts = _parse_int_list(args.tasks)
    thresholds = _parse_float_list(args.max_wall_ms)
    if thresholds and len(thresholds) != len(task_counts):
        raise ValueError("--max-wall-ms length must match --tasks length")

    cases: list[dict] = []
    failed = False
    for idx, task_count in enumerate(task_counts):
        case = _run_case(task_count, args.seed)
        max_wall = thresholds[idx] if thresholds else None
        case["max_wall_ms"] = max_wall
        if max_wall is not None:
            case["pass"] = case["wall_time_ms"] <= max_wall
            failed = failed or not case["pass"]
        else:
            case["pass"] = True
        cases.append(case)
        verdict = "PASS" if case["pass"] else "FAIL"
        print(
            f"[{verdict}] tasks={task_count} wall_ms={case['wall_time_ms']:.2f} "
            f"events={case['event_count']}"
        )

    report = {"seed": args.seed, "cases": cases}
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[INFO] wrote perf report: {output_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
