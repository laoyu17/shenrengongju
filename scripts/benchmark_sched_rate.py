"""Generate standard schedulability benchmark set and run stratified uplift gate."""

from __future__ import annotations

import argparse
import csv
import json
import random
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from rtos_sim import api as sim_api


TIER_ORDER = ("low", "medium", "high")
TIER_FACTOR_POOL: dict[str, tuple[float, ...]] = {
    "low": (0.55, 0.60, 0.75, 0.80),
    "medium": (0.85, 0.90, 0.95, 1.00),
    "high": (1.05, 1.10, 1.15, 1.20),
}
DEADLINE_VARIANTS = (1.50, 1.57, 1.65)
ARRIVAL_SHIFTS = (-0.05, 0.00, 0.05, 0.10)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _base_case_spec() -> dict[str, Any]:
    # Template from a validated precautious-sensitive case. Load factor controls difficulty.
    return {
        "version": "0.2",
        "platform": {
            "processor_types": [{"id": "CPU", "name": "cpu", "core_count": 1, "speed_factor": 1.0}],
            "cores": [{"id": "c0", "type_id": "CPU", "speed_factor": 1.0}],
        },
        "resources": [],
        "tasks": [
            {
                "id": "t0",
                "name": "t0",
                "task_type": "time_deterministic",
                "period": 16.0,
                "deadline": 11.95,
                "arrival": 0.48,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [
                            {"id": "g00", "index": 1, "wcet": 3.25, "required_resources": [], "mapping_hint": "c0"},
                            {"id": "g01", "index": 2, "wcet": 0.43, "required_resources": [], "mapping_hint": "c0"},
                        ],
                    }
                ],
            },
            {
                "id": "t1",
                "name": "t1",
                "task_type": "time_deterministic",
                "period": 16.0,
                "deadline": 10.29,
                "arrival": 0.65,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [{"id": "g00", "index": 1, "wcet": 2.65, "required_resources": []}],
                    }
                ],
            },
            {
                "id": "t2",
                "name": "t2",
                "task_type": "time_deterministic",
                "period": 8.0,
                "deadline": 1.57,
                "arrival": 3.76,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [
                            {"id": "g00", "index": 1, "wcet": 0.77, "required_resources": [], "mapping_hint": "c0"},
                            {"id": "g01", "index": 2, "wcet": 0.44, "required_resources": []},
                        ],
                    }
                ],
            },
        ],
        "scheduler": {"name": "edf", "params": {}},
        "sim": {"duration": 60.0, "seed": 1},
        "planning": {"planner": "np_edf", "task_scope": "sync_only"},
    }


def _build_case_spec(
    *,
    load_factor: float,
    case_seed: int,
    deadline_variant: float,
    arrival_shift: float,
) -> dict[str, Any]:
    spec = deepcopy(_base_case_spec())
    for task in spec["tasks"]:
        for subtask in task["subtasks"]:
            for segment in subtask["segments"]:
                segment["wcet"] = round(float(segment["wcet"]) * load_factor, 3)
    spec["tasks"][2]["deadline"] = float(deadline_variant)
    spec["tasks"][2]["arrival"] = round(float(spec["tasks"][2]["arrival"]) + arrival_shift, 2)
    spec["sim"]["seed"] = int(case_seed)
    return spec


def _total_utilization(spec: dict[str, Any]) -> float:
    total = 0.0
    for task in spec.get("tasks", []):
        period = float(task.get("period") or 0.0)
        if period <= 0.0:
            continue
        wcet_sum = 0.0
        for subtask in task.get("subtasks", []):
            for segment in subtask.get("segments", []):
                wcet_sum += float(segment.get("wcet") or 0.0)
        total += wcet_sum / period
    return round(total, 9)


def _relative_uplift(baseline_rate: float, candidate_rate: float) -> float:
    if baseline_rate > 1e-12:
        return (candidate_rate - baseline_rate) / baseline_rate
    return 1.0 if candidate_rate > 0.0 else 0.0


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate fixed-seed stratified sched-rate benchmark set and apply macro-uplift gate."
    )
    parser.add_argument("--output-dir", default="artifacts/sched-rate-benchmark", help="output root directory")
    parser.add_argument("--seed", type=int, default=20260304, help="deterministic seed for case selection")
    parser.add_argument("--cases-per-tier", type=int, default=4, help="number of configs per load tier")
    parser.add_argument("--baseline", default="np_edf", help="baseline planner name")
    parser.add_argument(
        "--candidates",
        default="np_dm,precautious_dm,lp",
        help="comma-separated candidate planners",
    )
    parser.add_argument(
        "--task-scope",
        default="sync_only",
        help="planning scope passed to benchmark: sync_only|sync_and_dynamic_rt|all",
    )
    parser.add_argument("--lp-objective", default="response_time", help="LP objective when candidate includes lp")
    parser.add_argument("--lp-time-limit", type=float, default=30.0, help="LP time limit in seconds")
    parser.add_argument("--wcrt-max-iterations", type=int, default=64, help="max WCRT fixed-point iterations")
    parser.add_argument("--wcrt-epsilon", type=float, default=1e-9, help="WCRT fixed-point epsilon")
    parser.add_argument("--target-uplift", type=float, default=0.30, help="required macro uplift threshold")
    parser.add_argument("--strict", action="store_true", help="return non-zero when gate not met")
    parser.add_argument("--out-json", default="", help="benchmark report json path")
    parser.add_argument("--out-csv", default="", help="benchmark strata csv path")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cases_per_tier <= 0:
        print("[ERROR] --cases-per-tier must be > 0")
        return 1

    output_dir = Path(args.output_dir)
    out_json = Path(args.out_json) if args.out_json else output_dir / "sched-rate-benchmark.json"
    out_csv = Path(args.out_csv) if args.out_csv else output_dir / "sched-rate-benchmark.csv"

    candidate_list = [item.strip() for item in args.candidates.split(",") if item.strip()]
    if not candidate_list:
        print("[ERROR] --candidates cannot be empty")
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    configs_dir = output_dir / "configs"
    case_manifest: list[dict[str, Any]] = []
    tier_paths: dict[str, list[str]] = {tier: [] for tier in TIER_ORDER}

    for tier_idx, tier in enumerate(TIER_ORDER):
        tier_dir = configs_dir / tier
        tier_dir.mkdir(parents=True, exist_ok=True)
        pool = list(TIER_FACTOR_POOL[tier])
        random.Random(args.seed + tier_idx * 97).shuffle(pool)

        for case_idx in range(args.cases_per_tier):
            load_factor = pool[case_idx % len(pool)]
            deadline_variant = DEADLINE_VARIANTS[(case_idx + tier_idx) % len(DEADLINE_VARIANTS)]
            arrival_shift = ARRIVAL_SHIFTS[(case_idx + tier_idx) % len(ARRIVAL_SHIFTS)]
            case_seed = args.seed + tier_idx * 1000 + case_idx
            spec = _build_case_spec(
                load_factor=load_factor,
                case_seed=case_seed,
                deadline_variant=deadline_variant,
                arrival_shift=arrival_shift,
            )
            file_path = tier_dir / f"{tier}-{case_idx + 1:02d}.yaml"
            file_path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
            resolved = str(file_path.resolve())
            tier_paths[tier].append(resolved)
            case_manifest.append(
                {
                    "tier": tier,
                    "case_id": f"{tier}-{case_idx + 1:02d}",
                    "path": resolved,
                    "load_factor": load_factor,
                    "deadline_variant": deadline_variant,
                    "arrival_shift": arrival_shift,
                    "utilization": _total_utilization(spec),
                    "seed": case_seed,
                }
            )

    all_paths: list[str] = []
    for tier in TIER_ORDER:
        all_paths.extend(tier_paths[tier])

    benchmark_kwargs = {
        "baseline": args.baseline,
        "candidates": candidate_list,
        "task_scope": args.task_scope,
        "include_non_rt": False,
        "horizon": None,
        "lp_objective": args.lp_objective,
        "lp_time_limit_seconds": args.lp_time_limit,
        "wcrt_max_iterations": args.wcrt_max_iterations,
        "wcrt_epsilon": args.wcrt_epsilon,
    }
    overall = sim_api.benchmark_sched_rate(all_paths, **benchmark_kwargs)

    strata_rows: list[dict[str, Any]] = []
    for tier in TIER_ORDER:
        report = sim_api.benchmark_sched_rate(tier_paths[tier], **benchmark_kwargs)
        baseline_rate = float(report.get("baseline_schedulable_rate", 0.0))
        best_candidate_rate = float(report.get("best_candidate_schedulable_rate", 0.0))
        candidate_only_rate = float(report.get("candidate_only_schedulable_rate", 0.0))
        best_candidate_uplift = _relative_uplift(baseline_rate, best_candidate_rate)
        candidate_only_uplift = _relative_uplift(baseline_rate, candidate_only_rate)
        tier_cases = [item for item in case_manifest if item["tier"] == tier]
        strata_rows.append(
            {
                "tier": tier,
                "case_count": int(report.get("total_cases", 0)),
                "utilization_min": min(item["utilization"] for item in tier_cases),
                "utilization_max": max(item["utilization"] for item in tier_cases),
                "baseline_schedulable_rate": round(baseline_rate, 9),
                "best_candidate_schedulable_rate": round(best_candidate_rate, 9),
                "candidate_only_schedulable_rate": round(candidate_only_rate, 9),
                "uplift": round(best_candidate_uplift, 9),
                "candidate_only_uplift": round(candidate_only_uplift, 9),
            }
        )

    macro_uplift = round(sum(item["candidate_only_uplift"] for item in strata_rows) / len(strata_rows), 9)
    macro_best_candidate_uplift = round(sum(item["uplift"] for item in strata_rows) / len(strata_rows), 9)
    gate_pass = macro_uplift >= float(args.target_uplift)
    payload = {
        "generated_at_utc": _utc_now(),
        "seed": int(args.seed),
        "cases_per_tier": int(args.cases_per_tier),
        "baseline": args.baseline,
        "candidates": candidate_list,
        "task_scope": args.task_scope,
        "target_uplift": float(args.target_uplift),
        "macro_uplift": macro_uplift,
        "macro_best_candidate_uplift": macro_best_candidate_uplift,
        "gate_metric": "candidate_only_uplift",
        "gate_pass": gate_pass,
        "tiers": strata_rows,
        "overall": overall,
        "cases": case_manifest,
    }
    _write_json(out_json, payload)
    _write_csv(out_csv, strata_rows)
    (output_dir / "config-list.txt").write_text("\n".join(all_paths) + "\n", encoding="utf-8")

    print(
        "[OK] benchmark generated and evaluated, "
        f"cases={len(all_paths)}, macro_uplift={macro_uplift}, "
        f"target={args.target_uplift}, gate_pass={gate_pass}, json={out_json}, csv={out_csv}"
    )
    if args.strict and not gate_pass:
        print(f"[ERROR] macro uplift target not met: target={args.target_uplift}, actual={macro_uplift}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
