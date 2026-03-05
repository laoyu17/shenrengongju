"""Build offline paper datasets from existing artifacts.

This script intentionally stays outside product runtime codepaths.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

DEFAULT_SCENARIOS = [
    "at01_single_dag_single_core",
    "at02_resource_mutex",
    "at06_time_deterministic",
    "at07_heterogeneous_multicore",
    "at09_table_based_etm",
    "at10_arrival_process",
]
DEFAULT_SEEDS = [7, 11, 23, 47, 97, 131, 197, 233, 257, 307]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"json root must be object: {path}")
    return payload


def _run(cmd: list[str], cwd: Path) -> None:
    result = subprocess.run(cmd, cwd=str(cwd), check=False, capture_output=True, text=True)  # noqa: S603
    if result.returncode != 0:
        command = " ".join(cmd)
        raise RuntimeError(
            f"command failed ({result.returncode}): {command}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def _as_pipe_join(value: Any) -> str:
    if isinstance(value, list):
        return "|".join(str(item) for item in value)
    return str(value)


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _git_sha(project_root: Path) -> str:
    result = subprocess.run(  # noqa: S603
        ["git", "rev-parse", "HEAD"],
        cwd=str(project_root),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return "unknown"


def regenerate_artifacts(
    *,
    project_root: Path,
    artifacts_root: Path,
    out_root: Path,
    scenarios: list[str],
    perf_seeds: list[int],
) -> None:
    py = sys.executable
    raw_runs_root = out_root / "raw" / "runs"
    raw_perf_root = out_root / "raw" / "perf"
    raw_runs_root.mkdir(parents=True, exist_ok=True)
    raw_perf_root.mkdir(parents=True, exist_ok=True)

    _run(
        [
            py,
            "scripts/quality_snapshot.py",
            "--output",
            str(artifacts_root / "quality" / "quality-snapshot.json"),
            "--coverage-json",
            str(artifacts_root / "quality" / "coverage.json"),
        ],
        project_root,
    )

    _run(
        [
            py,
            "scripts/research_case_suite.py",
            "--cases",
            "examples/research_counterexamples.json",
            "--out-json",
            str(artifacts_root / "research" / "research-case-summary.json"),
            "--out-csv",
            str(artifacts_root / "research" / "research-case-summary.csv"),
            "--audit-dir",
            str(artifacts_root / "research" / "case-audits"),
        ],
        project_root,
    )

    _run(
        [
            py,
            "scripts/research_report.py",
            "--audit",
            str(artifacts_root / "research" / "audit.json"),
            "--relations",
            str(artifacts_root / "research" / "model_relations.json"),
            "--quality",
            str(artifacts_root / "quality" / "quality-snapshot.json"),
            "--out-markdown",
            str(artifacts_root / "research" / "research-report.md"),
            "--out-csv",
            str(artifacts_root / "research" / "research-summary.csv"),
            "--out-json",
            str(artifacts_root / "research" / "research-report.json"),
        ],
        project_root,
    )

    for scenario in scenarios:
        cfg = f"examples/{scenario}.yaml"
        run_out = raw_runs_root / scenario
        run_out.mkdir(parents=True, exist_ok=True)
        _run(
            [
                py,
                "-m",
                "rtos_sim.cli.main",
                "run",
                "-c",
                cfg,
                "--events-out",
                str(run_out / "events.jsonl"),
                "--metrics-out",
                str(run_out / "metrics.json"),
                "--audit-out",
                str(run_out / "audit.json"),
            ],
            project_root,
        )
        _run(
            [
                py,
                "-m",
                "rtos_sim.cli.main",
                "inspect-model",
                "-c",
                cfg,
                "--out-json",
                str(run_out / "model_relations.json"),
                "--out-csv",
                str(run_out / "model_relations.csv"),
                "--strict-on-fail",
            ],
            project_root,
        )

    for seed in perf_seeds:
        out_path = raw_perf_root / f"perf_seed_{seed}.json"
        _run(
            [
                py,
                "scripts/perf_baseline.py",
                "--tasks",
                "100,300,1000",
                "--seed",
                str(seed),
                "--output",
                str(out_path),
            ],
            project_root,
        )


def collect_run_rows(artifacts_root: Path, out_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    raw_runs_root = out_root / "raw" / "runs"

    if raw_runs_root.exists():
        for scenario_dir in sorted(raw_runs_root.iterdir()):
            if not scenario_dir.is_dir():
                continue
            metrics_path = scenario_dir / "metrics.json"
            audit_path = scenario_dir / "audit.json"
            rel_path = scenario_dir / "model_relations.json"
            if not metrics_path.exists():
                continue
            metrics = _read_json(metrics_path)
            audit = _read_json(audit_path) if audit_path.exists() else {}
            relations = _read_json(rel_path) if rel_path.exists() else {}
            rows.append(
                {
                    "scenario": scenario_dir.name,
                    "seed": "config",
                    "jobs_released": metrics.get("jobs_released"),
                    "jobs_completed": metrics.get("jobs_completed"),
                    "deadline_miss_count": metrics.get("deadline_miss_count"),
                    "avg_response_time": metrics.get("avg_response_time"),
                    "avg_lateness": metrics.get("avg_lateness"),
                    "preempt_count": metrics.get("preempt_count"),
                    "migrate_count": metrics.get("migrate_count"),
                    "event_count": metrics.get("event_count"),
                    "max_time": metrics.get("max_time"),
                    "audit_status": audit.get("status", "unknown"),
                    "audit_issue_count": audit.get("issue_count", 0),
                    "relation_status": relations.get("status", "unknown"),
                }
            )

    if rows:
        return rows

    for metrics_path in sorted(artifacts_root.glob("metrics*.json")):
        metrics = _read_json(metrics_path)
        scenario = metrics_path.stem.replace("metrics-", "")
        rows.append(
            {
                "scenario": scenario,
                "seed": "legacy",
                "jobs_released": metrics.get("jobs_released"),
                "jobs_completed": metrics.get("jobs_completed"),
                "deadline_miss_count": metrics.get("deadline_miss_count"),
                "avg_response_time": metrics.get("avg_response_time"),
                "avg_lateness": metrics.get("avg_lateness"),
                "preempt_count": metrics.get("preempt_count"),
                "migrate_count": metrics.get("migrate_count"),
                "event_count": metrics.get("event_count"),
                "max_time": metrics.get("max_time"),
                "audit_status": "unknown",
                "audit_issue_count": 0,
                "relation_status": "unknown",
            }
        )
    return rows


def collect_audit_rows(artifacts_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    summary_path = artifacts_root / "research" / "research-case-summary.json"
    if not summary_path.exists():
        return rows

    summary = _read_json(summary_path)
    case_audit_dir = artifacts_root / "research" / "case-audits"

    for case in summary.get("cases", []):
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("case_id") or "")
        base = {
            "case_id": case_id,
            "group": case.get("group", ""),
            "expected_status": case.get("expected_status", ""),
            "actual_status": case.get("actual_status", ""),
            "matched": bool(case.get("matched", False)),
            "expected_failed_checks": _as_pipe_join(case.get("expected_failed_checks", [])),
            "actual_failed_checks": _as_pipe_join(case.get("actual_failed_checks", [])),
            "missing_expected_checks": _as_pipe_join(case.get("missing_expected_checks", [])),
            "unexpected_actual_checks": _as_pipe_join(case.get("unexpected_actual_checks", [])),
        }

        audit_path = case_audit_dir / f"{case_id}.audit.json"
        if not case_id or not audit_path.exists():
            rows.append({**base, "check_name": "__case__", "check_passed": "", "issue_count": ""})
            continue

        audit = _read_json(audit_path)
        checks = audit.get("checks")
        if not isinstance(checks, dict):
            rows.append({**base, "check_name": "__case__", "check_passed": "", "issue_count": ""})
            continue

        for check_name, result in sorted(checks.items()):
            if not isinstance(result, dict):
                continue
            rows.append(
                {
                    **base,
                    "check_name": check_name,
                    "check_passed": result.get("passed"),
                    "issue_count": result.get("issue_count", 0),
                    "sample_event_ids": _as_pipe_join(result.get("sample_event_ids", [])),
                }
            )

    return rows


def collect_perf_rows(artifacts_root: Path, out_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    perf_root = out_root / "raw" / "perf"
    perf_reports = sorted(perf_root.glob("perf_seed_*.json"))

    if not perf_reports:
        fallback = artifacts_root / "perf" / "perf-baseline.json"
        if fallback.exists():
            perf_reports = [fallback]

    for report_path in perf_reports:
        report = _read_json(report_path)
        seed = report.get("seed")
        if seed is None:
            stem = report_path.stem
            if stem.startswith("perf_seed_"):
                seed = stem.replace("perf_seed_", "")
            else:
                seed = "unknown"
        for case in report.get("cases", []):
            if not isinstance(case, dict):
                continue
            rows.append(
                {
                    "report": report_path.name,
                    "seed": seed,
                    "case_name": case.get("case_name", ""),
                    "task_count": case.get("task_count", 0),
                    "wall_time_ms": case.get("wall_time_ms", 0.0),
                    "event_count": case.get("event_count", 0),
                    "jobs_released": case.get("jobs_released", 0),
                    "jobs_completed": case.get("jobs_completed", 0),
                    "pass": case.get("pass", True),
                    "max_wall_ms": case.get("max_wall_ms"),
                }
            )

    return rows


def collect_proof_asset_rows(artifacts_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    audit_path = artifacts_root / "research" / "audit.json"
    if audit_path.exists():
        audit = _read_json(audit_path)
        for section in ["protocol_proof_assets", "time_deterministic_proof_assets"]:
            payload = audit.get(section)
            if not isinstance(payload, dict):
                continue
            for key, value in sorted(payload.items()):
                if isinstance(value, (dict, list)):
                    continue
                rows.append(
                    {
                        "source": audit_path.name,
                        "section": section,
                        "metric": key,
                        "value": value,
                    }
                )

    report_path = artifacts_root / "research" / "research-report.json"
    if report_path.exists():
        report = _read_json(report_path)
        payload = report.get("proof_assets")
        if isinstance(payload, dict):
            for key, value in sorted(payload.items()):
                if isinstance(value, (dict, list)):
                    continue
                rows.append(
                    {
                        "source": report_path.name,
                        "section": "proof_assets",
                        "metric": key,
                        "value": value,
                    }
                )
    return rows


def build_meta(
    *,
    project_root: Path,
    artifacts_root: Path,
    seeds: list[int],
    scenarios: list[str],
    regenerate: bool,
) -> dict[str, Any]:
    snapshot_path = artifacts_root / "quality" / "quality-snapshot.json"
    snapshot = _read_json(snapshot_path) if snapshot_path.exists() else {}
    pytest_block = snapshot.get("pytest") if isinstance(snapshot.get("pytest"), dict) else {}
    coverage_block = snapshot.get("coverage") if isinstance(snapshot.get("coverage"), dict) else {}

    return {
        "generated_at_utc": _utc_now(),
        "git_sha": snapshot.get("git_sha") or _git_sha(project_root),
        "quality_snapshot": str(snapshot_path),
        "pytest_passed": _safe_int(pytest_block.get("passed")),
        "coverage_line_rate": _safe_float(coverage_block.get("line_rate")),
        "scenarios": scenarios,
        "seeds": seeds,
        "regenerate": regenerate,
    }


def build_figure_manifest() -> dict[str, Any]:
    return {
        "main": {
            "fig01": ["meta.json"],
            "fig02": ["audit_table.csv"],
            "fig03": ["audit_table.csv"],
            "fig04": ["proof_assets_table.csv", "meta.json"],
            "fig05": ["proof_assets_table.csv"],
            "fig06": ["audit_table.csv"],
            "fig07": ["perf_table.csv"],
            "fig08": ["meta.json", "run_table.csv", "audit_table.csv"],
        },
        "appendix": {
            "appa1": ["meta.json"],
            "appa2": ["run_table.csv"],
            "appa3": ["run_table.csv"],
            "appa4": ["run_table.csv"],
            "appa5": ["meta.json"],
            "appa6": ["meta.json"],
        },
        "concept": {
            "ga1": ["../scripts/paper_assets/prompt_nano_banana.md"],
        },
    }


def parse_int_list(raw: str) -> list[int]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return [int(item) for item in values]


def parse_str_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build paper dataset tables from artifacts")
    parser.add_argument("--artifacts-root", default="artifacts", help="artifacts root directory")
    parser.add_argument("--out-root", default="artifacts/paper_data", help="output dataset directory")
    parser.add_argument(
        "--seeds",
        default=",".join(str(item) for item in DEFAULT_SEEDS),
        help="comma-separated seeds for perf baseline regeneration",
    )
    parser.add_argument(
        "--scenarios",
        default=",".join(DEFAULT_SCENARIOS),
        help="comma-separated scenario names (without .yaml)",
    )
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="rerun quality/research/scenario/perf commands before dataset export",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parents[2]
    artifacts_root = (project_root / args.artifacts_root).resolve()
    out_root = (project_root / args.out_root).resolve()
    seeds = parse_int_list(args.seeds)
    scenarios = parse_str_list(args.scenarios)

    if args.regenerate:
        regenerate_artifacts(
            project_root=project_root,
            artifacts_root=artifacts_root,
            out_root=out_root,
            scenarios=scenarios,
            perf_seeds=seeds,
        )

    out_root.mkdir(parents=True, exist_ok=True)

    run_rows = collect_run_rows(artifacts_root, out_root)
    audit_rows = collect_audit_rows(artifacts_root)
    perf_rows = collect_perf_rows(artifacts_root, out_root)
    proof_rows = collect_proof_asset_rows(artifacts_root)
    meta = build_meta(
        project_root=project_root,
        artifacts_root=artifacts_root,
        seeds=seeds,
        scenarios=scenarios,
        regenerate=args.regenerate,
    )
    figure_manifest = build_figure_manifest()

    _write_csv(out_root / "run_table.csv", run_rows)
    _write_csv(out_root / "audit_table.csv", audit_rows)
    _write_csv(out_root / "perf_table.csv", perf_rows)
    _write_csv(out_root / "proof_assets_table.csv", proof_rows)
    (out_root / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_root / "figure_manifest.json").write_text(
        json.dumps(figure_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        "[INFO] paper dataset built "
        f"run_rows={len(run_rows)} audit_rows={len(audit_rows)} "
        f"perf_rows={len(perf_rows)} proof_rows={len(proof_rows)} out={out_root}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
