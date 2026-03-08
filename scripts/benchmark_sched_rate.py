"""Generate schedulability benchmark profiles and apply dual hard gates."""

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
        description="Generate fixed-seed sched-rate benchmark profiles and apply dual hard gates."
    )
    parser.add_argument("--output-dir", default="artifacts/sched-rate-benchmark", help="output root directory")
    parser.add_argument("--seed", type=int, default=20260304, help="deterministic seed for case selection")
    parser.add_argument("--cases-per-tier", type=int, default=4, help="number of generated configs per load tier")
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
    parser.add_argument("--target-uplift", type=float, default=0.30, help="required uplift threshold for both gates")
    parser.add_argument(
        "--docx-config-list",
        default="review/frozen/sched_rate/config-list.txt",
        help="config list used by docx_mixed frozen profile",
    )
    parser.add_argument("--strict", action="store_true", help="return non-zero when any hard gate fails")
    parser.add_argument("--out-json", default="", help="benchmark report json path")
    parser.add_argument("--out-csv", default="", help="benchmark strata csv path")
    return parser


def _resolve_benchmark_kwargs(args: argparse.Namespace, candidate_list: list[str]) -> dict[str, Any]:
    return {
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


def _load_config_list(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"config-list not found: {path}")

    resolved_paths: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        candidate = Path(line)
        search_paths: list[Path] = [candidate]
        if not candidate.is_absolute():
            search_paths.append(path.parent / candidate)

        resolved: Path | None = None
        for probe in search_paths:
            if probe.exists():
                resolved = probe.resolve()
                break
        if resolved is None:
            raise FileNotFoundError(f"config listed but missing: {line}")
        resolved_paths.append(str(resolved))

    if not resolved_paths:
        raise ValueError(f"config-list is empty: {path}")
    return resolved_paths


def _build_standard_seeded_profile(
    *,
    args: argparse.Namespace,
    output_dir: Path,
    benchmark_kwargs: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
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

    overall = sim_api.benchmark_sched_rate(all_paths, **benchmark_kwargs)

    strata_rows: list[dict[str, Any]] = []
    for tier in TIER_ORDER:
        report = sim_api.benchmark_sched_rate(tier_paths[tier], **benchmark_kwargs)
        tier_cases = [item for item in case_manifest if item["tier"] == tier]
        strata_rows.append(
            {
                "profile": "standard_seeded",
                "tier": tier,
                "case_count": int(report.get("total_cases", 0)),
                "empty_scope_case_count": int(report.get("empty_scope_case_count", 0)),
                "non_empty_case_count": int(report.get("non_empty_case_count", 0)),
                "utilization_min": min(item["utilization"] for item in tier_cases),
                "utilization_max": max(item["utilization"] for item in tier_cases),
                "baseline_schedulable_rate": float(report.get("baseline_schedulable_rate", 0.0)),
                "best_candidate_schedulable_rate": float(report.get("best_candidate_schedulable_rate", 0.0)),
                "candidate_only_schedulable_rate": float(report.get("candidate_only_schedulable_rate", 0.0)),
                "non_empty_baseline_schedulable_rate": float(
                    report.get("non_empty_baseline_schedulable_rate", 0.0)
                ),
                "non_empty_best_candidate_schedulable_rate": float(
                    report.get("non_empty_best_candidate_schedulable_rate", 0.0)
                ),
                "non_empty_candidate_only_schedulable_rate": float(
                    report.get("non_empty_candidate_only_schedulable_rate", 0.0)
                ),
                "uplift": float(report.get("uplift", 0.0)),
                "candidate_only_uplift": float(report.get("candidate_only_uplift", 0.0)),
                "non_empty_uplift": float(report.get("non_empty_uplift", 0.0)),
                "non_empty_candidate_only_uplift": float(
                    report.get("non_empty_candidate_only_uplift", 0.0)
                ),
            }
        )

    macro_uplift = round(
        sum(item["non_empty_candidate_only_uplift"] for item in strata_rows) / len(strata_rows),
        9,
    )
    macro_best_candidate_uplift = round(
        sum(item["non_empty_uplift"] for item in strata_rows) / len(strata_rows),
        9,
    )
    non_empty_case_count = int(overall.get("non_empty_case_count", 0))
    gate_pass = macro_uplift >= float(args.target_uplift) and non_empty_case_count > 0

    profile_payload = {
        "profile": "standard_seeded",
        "seed": int(args.seed),
        "cases_per_tier": int(args.cases_per_tier),
        "target_uplift": float(args.target_uplift),
        "gate_metric": "macro_uplift",
        "macro_uplift": macro_uplift,
        "macro_best_candidate_uplift": macro_best_candidate_uplift,
        "gate_pass": gate_pass,
        "tiers": strata_rows,
        "overall": overall,
        "cases": case_manifest,
    }
    return profile_payload, strata_rows, all_paths


def _build_docx_mixed_profile(
    *,
    args: argparse.Namespace,
    benchmark_kwargs: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    config_list_path = Path(args.docx_config_list)
    config_paths = _load_config_list(config_list_path)
    overall = sim_api.benchmark_sched_rate(config_paths, **benchmark_kwargs)

    gate_value = float(overall.get("candidate_only_uplift", 0.0))
    non_empty_case_count = int(overall.get("non_empty_case_count", 0))
    gate_pass = gate_value >= float(args.target_uplift) and non_empty_case_count > 0

    row = {
        "profile": "docx_mixed",
        "tier": "frozen",
        "case_count": int(overall.get("total_cases", 0)),
        "empty_scope_case_count": int(overall.get("empty_scope_case_count", 0)),
        "non_empty_case_count": non_empty_case_count,
        "utilization_min": None,
        "utilization_max": None,
        "baseline_schedulable_rate": float(overall.get("baseline_schedulable_rate", 0.0)),
        "best_candidate_schedulable_rate": float(overall.get("best_candidate_schedulable_rate", 0.0)),
        "candidate_only_schedulable_rate": float(overall.get("candidate_only_schedulable_rate", 0.0)),
        "non_empty_baseline_schedulable_rate": float(overall.get("non_empty_baseline_schedulable_rate", 0.0)),
        "non_empty_best_candidate_schedulable_rate": float(
            overall.get("non_empty_best_candidate_schedulable_rate", 0.0)
        ),
        "non_empty_candidate_only_schedulable_rate": float(
            overall.get("non_empty_candidate_only_schedulable_rate", 0.0)
        ),
        "uplift": float(overall.get("uplift", 0.0)),
        "candidate_only_uplift": gate_value,
        "non_empty_uplift": float(overall.get("non_empty_uplift", 0.0)),
        "non_empty_candidate_only_uplift": float(overall.get("non_empty_candidate_only_uplift", 0.0)),
    }

    profile_payload = {
        "profile": "docx_mixed",
        "variant": "frozen",
        "source_config_list": str(config_list_path),
        "target_uplift": float(args.target_uplift),
        "gate_metric": "candidate_only_uplift",
        "gate_value": gate_value,
        "gate_pass": gate_pass,
        "overall": overall,
    }
    return profile_payload, [row]


def _profile_gate_failure_reasons(profile_name: str, profile_payload: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    target = float(profile_payload.get("target_uplift", 0.0))
    overall = profile_payload.get("overall", {})
    if not isinstance(overall, dict):
        overall = {}
    non_empty_case_count = int(overall.get("non_empty_case_count", 0))

    if profile_name == "standard_seeded":
        metric = float(profile_payload.get("macro_uplift", 0.0))
        if metric < target:
            reasons.append(f"macro_uplift<{target} (actual={metric})")
    else:
        metric = float(profile_payload.get("gate_value", 0.0))
        if metric < target:
            reasons.append(f"candidate_only_uplift<{target} (actual={metric})")

    if non_empty_case_count <= 0:
        reasons.append("non_empty_case_count<=0")
    return reasons


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
    benchmark_kwargs = _resolve_benchmark_kwargs(args, candidate_list)

    try:
        standard_profile, standard_rows, standard_all_paths = _build_standard_seeded_profile(
            args=args,
            output_dir=output_dir,
            benchmark_kwargs=benchmark_kwargs,
        )
        docx_profile, docx_rows = _build_docx_mixed_profile(
            args=args,
            benchmark_kwargs=benchmark_kwargs,
        )
    except Exception as exc:
        print(f"[ERROR] benchmark generation failed: {exc}")
        return 1

    profiles = {
        "standard_seeded": standard_profile,
        "docx_mixed": docx_profile,
    }
    all_gate_pass = all(bool(profile.get("gate_pass")) for profile in profiles.values())
    top_gate_metric = str(docx_profile["gate_metric"])
    top_gate_value = float(docx_profile["gate_value"])
    top_gate_pass = bool(docx_profile["gate_pass"])

    payload = {
        "generated_at_utc": _utc_now(),
        "seed": int(args.seed),
        "cases_per_tier": int(args.cases_per_tier),
        "baseline": args.baseline,
        "candidates": candidate_list,
        "task_scope": args.task_scope,
        "target_uplift": float(args.target_uplift),
        "profiles": profiles,
        # Backward-compatible aliases (standard profile)
        "macro_uplift": standard_profile["macro_uplift"],
        "macro_best_candidate_uplift": standard_profile["macro_best_candidate_uplift"],
        "candidate_only_uplift": top_gate_value,
        "gate_metric": top_gate_metric,
        "gate_value": top_gate_value,
        "gate_pass": top_gate_pass,
        "dual_gate_pass": all_gate_pass,
        "tiers": standard_profile["tiers"],
        "overall": standard_profile["overall"],
        "cases": standard_profile["cases"],
    }

    csv_rows = [*standard_rows, *docx_rows]
    _write_json(out_json, payload)
    _write_csv(out_csv, csv_rows)
    (output_dir / "config-list.txt").write_text("\n".join(standard_all_paths) + "\n", encoding="utf-8")

    print(
        "[OK] benchmark profiles generated, "
        f"gate_metric={top_gate_metric}, gate_value={top_gate_value}, gate_pass={top_gate_pass}, "
        f"standard_macro_uplift={standard_profile['macro_uplift']}, "
        f"all_gate_pass={all_gate_pass}, json={out_json}, csv={out_csv}"
    )

    if args.strict and not top_gate_pass:
        reasons = _profile_gate_failure_reasons("docx_mixed", docx_profile)
        detail = ", ".join(reasons) if reasons else "unknown"
        print("[ERROR] benchmark gate not met: docx_mixed(" + detail + ")")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
