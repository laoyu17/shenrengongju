"""Run audit against research counterexample fixtures."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from rtos_sim.analysis import build_audit_report


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"json root must be object: {path}")
    return payload


def _normalize_check_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    checks: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            checks.append(item.strip())
    return sorted(set(checks))


def _case_actual_failed_checks(report: dict[str, Any]) -> list[str]:
    checks = report.get("checks")
    if not isinstance(checks, dict):
        return []
    failed: list[str] = []
    for name, result in checks.items():
        if isinstance(result, dict) and result.get("passed") is False:
            failed.append(str(name))
    return sorted(failed)


def run_research_case_suite(
    *,
    manifest: dict[str, Any],
    audit_dir: Path,
) -> dict[str, Any]:
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("manifest requires non-empty cases list")

    audit_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []

    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"cases[{index}] must be object")
        case_id = str(case.get("id") or f"case_{index:03d}")
        group = str(case.get("group") or "ungrouped")
        scheduler_name = case.get("scheduler_name")
        events = case.get("events")
        if not isinstance(events, list):
            raise ValueError(f"case {case_id} requires events list")

        expected = case.get("expected")
        if not isinstance(expected, dict):
            expected = {}
        expected_status = str(expected.get("status") or "pass")
        expected_failed_checks = _normalize_check_list(expected.get("failed_checks"))

        report = build_audit_report(events, scheduler_name=scheduler_name if isinstance(scheduler_name, str) else None)
        report_path = audit_dir / f"{case_id}.audit.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        actual_status = str(report.get("status"))
        actual_failed_checks = _case_actual_failed_checks(report)
        missing_expected_checks = [name for name in expected_failed_checks if name not in actual_failed_checks]
        unexpected_actual_checks = [name for name in actual_failed_checks if name not in expected_failed_checks]
        matched = (
            actual_status == expected_status
            and not missing_expected_checks
            and not unexpected_actual_checks
        )

        rows.append(
            {
                "case_id": case_id,
                "group": group,
                "expected_status": expected_status,
                "actual_status": actual_status,
                "expected_failed_checks": expected_failed_checks,
                "actual_failed_checks": actual_failed_checks,
                "missing_expected_checks": missing_expected_checks,
                "unexpected_actual_checks": unexpected_actual_checks,
                "matched": matched,
                "audit_report_path": str(report_path),
            }
        )

    matched_count = sum(1 for row in rows if row["matched"])
    mismatched = [row for row in rows if not row["matched"]]

    return {
        "suite_version": "0.2",
        "case_manifest_version": manifest.get("version"),
        "total_cases": len(rows),
        "matched_cases": matched_count,
        "mismatched_cases": len(mismatched),
        "status": "pass" if not mismatched else "fail",
        "cases": rows,
    }


def _write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "case_id",
        "group",
        "expected_status",
        "actual_status",
        "matched",
        "expected_failed_checks",
        "actual_failed_checks",
        "missing_expected_checks",
        "unexpected_actual_checks",
        "audit_report_path",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **row,
                    "expected_failed_checks": "|".join(row.get("expected_failed_checks", [])),
                    "actual_failed_checks": "|".join(row.get("actual_failed_checks", [])),
                    "missing_expected_checks": "|".join(row.get("missing_expected_checks", [])),
                    "unexpected_actual_checks": "|".join(row.get("unexpected_actual_checks", [])),
                }
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run research counterexample audit suite")
    parser.add_argument(
        "--cases",
        default="examples/research_counterexamples.json",
        help="counterexample manifest path",
    )
    parser.add_argument(
        "--out-json",
        default="artifacts/research/research-case-summary.json",
        help="summary json output path",
    )
    parser.add_argument(
        "--out-csv",
        default="artifacts/research/research-case-summary.csv",
        help="summary csv output path",
    )
    parser.add_argument(
        "--audit-dir",
        default="artifacts/research/case-audits",
        help="directory for per-case audit reports",
    )
    parser.add_argument(
        "--allow-mismatch",
        action="store_true",
        help="always exit 0 even if suite contains mismatches",
    )
    args = parser.parse_args(argv)

    manifest_path = Path(args.cases)
    manifest = _load_json(manifest_path)
    summary = run_research_case_suite(manifest=manifest, audit_dir=Path(args.audit_dir))

    out_json_path = Path(args.out_json)
    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    out_json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_summary_csv(Path(args.out_csv), summary["cases"])

    print(
        "[INFO] research case suite status="
        f"{summary['status']} matched={summary['matched_cases']}/{summary['total_cases']} out={out_json_path}"
    )

    if summary["status"] == "pass" or args.allow_mismatch:
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
