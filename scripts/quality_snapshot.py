"""Generate a machine-readable test/coverage snapshot for docs and review reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from typing import Any

from rtos_sim.analysis.quality_snapshot import build_quality_snapshot


def _run_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"coverage payload must be JSON object: {path}")
    return payload


def _resolve_git_sha() -> str | None:
    result = _run_command(["git", "rev-parse", "HEAD"])
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate pytest+coverage quality snapshot JSON")
    parser.add_argument(
        "--output",
        default="artifacts/quality/quality-snapshot.json",
        help="snapshot JSON output path",
    )
    parser.add_argument(
        "--coverage-json",
        default="artifacts/quality/coverage.json",
        help="pytest-cov JSON report path",
    )
    parser.add_argument(
        "--python-bin",
        default="python",
        help="python executable used to run pytest",
    )
    parser.add_argument(
        "--allow-fail",
        action="store_true",
        help="always exit 0 even when pytest command fails",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    output_path = Path(args.output)
    coverage_path = Path(args.coverage_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    coverage_path.parent.mkdir(parents=True, exist_ok=True)

    pytest_summary_command = [
        args.python_bin,
        "-m",
        "pytest",
        "--maxfail=1",
    ]
    summary_result = _run_command(pytest_summary_command)

    coverage_command = [
        args.python_bin,
        "-m",
        "pytest",
        "--cov=rtos_sim",
        f"--cov-report=json:{coverage_path}",
        "-q",
    ]
    coverage_result = _run_command(coverage_command)

    coverage_payload: dict[str, Any]
    if coverage_path.exists():
        coverage_payload = _read_json(coverage_path)
    else:
        coverage_payload = {
            "totals": {
                "num_statements": 0,
                "covered_lines": 0,
                "missing_lines": 0,
                "percent_covered": 0.0,
                "percent_covered_display": "0",
            }
        }

    snapshot = build_quality_snapshot(
        pytest_output=f"{summary_result.stdout}\n{summary_result.stderr}".strip(),
        coverage_payload=coverage_payload,
        command=" && ".join(
            [
                " ".join(pytest_summary_command),
                " ".join(coverage_command),
            ]
        ),
        git_sha=_resolve_git_sha(),
        command_exit_code=max(summary_result.returncode, coverage_result.returncode),
    )
    if not coverage_path.exists():
        snapshot["status"] = "fail"
        snapshot["warning"] = f"coverage report not found: {coverage_path}"

    output_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[INFO] wrote quality snapshot: {output_path}")

    if args.allow_fail:
        return 0
    if summary_result.returncode != 0:
        return summary_result.returncode
    if coverage_result.returncode != 0:
        return coverage_result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
