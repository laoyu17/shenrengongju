"""Generate a machine-readable test/coverage snapshot for docs and review reports."""

from __future__ import annotations

import argparse
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import subprocess
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_build_quality_snapshot():
    module_path = PROJECT_ROOT / "rtos_sim" / "analysis" / "quality_snapshot.py"
    spec = spec_from_file_location("quality_snapshot_module", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"unable to load quality snapshot module: {module_path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    build_fn = getattr(module, "build_quality_snapshot", None)
    if not callable(build_fn):
        raise ImportError("quality snapshot module missing callable build_quality_snapshot")
    return build_fn


build_quality_snapshot = _load_build_quality_snapshot()


def _run_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"coverage payload must be JSON object: {path}")
    return payload


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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
    parser.add_argument(
        "--pytest-output-file",
        default="",
        help="existing pytest output text path (used with --reuse-existing-artifacts)",
    )
    parser.add_argument(
        "--reuse-existing-artifacts",
        action="store_true",
        help="build snapshot from existing pytest output and coverage JSON without running pytest",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    output_path = Path(args.output)
    coverage_path = Path(args.coverage_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    coverage_path.parent.mkdir(parents=True, exist_ok=True)

    summary_exit_code = 0
    coverage_exit_code = 0
    pytest_output: str
    command: str
    if args.reuse_existing_artifacts:
        pytest_output_raw = str(args.pytest_output_file).strip()
        if not pytest_output_raw:
            raise ValueError("--pytest-output-file is required when --reuse-existing-artifacts is set")
        pytest_output_path = Path(pytest_output_raw)
        if not pytest_output_path.exists():
            raise FileNotFoundError(f"pytest output file not found: {pytest_output_path}")
        if not coverage_path.exists():
            raise FileNotFoundError(f"coverage report not found: {coverage_path}")

        pytest_output = _read_text(pytest_output_path).strip()
        coverage_payload = _read_json(coverage_path)
        command = (
            "reuse_existing_artifacts "
            f"pytest_output={pytest_output_path} coverage_json={coverage_path}"
        )
    else:
        pytest_summary_command = [
            args.python_bin,
            "-m",
            "pytest",
            "--maxfail=1",
        ]
        summary_result = _run_command(pytest_summary_command)
        summary_exit_code = summary_result.returncode

        coverage_command = [
            args.python_bin,
            "-m",
            "pytest",
            "--cov=rtos_sim",
            f"--cov-report=json:{coverage_path}",
            "-q",
        ]
        coverage_result = _run_command(coverage_command)
        coverage_exit_code = coverage_result.returncode

        pytest_output = f"{summary_result.stdout}\n{summary_result.stderr}".strip()
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
        command = " && ".join(
            [
                " ".join(pytest_summary_command),
                " ".join(coverage_command),
            ]
        )

    snapshot = build_quality_snapshot(
        pytest_output=pytest_output,
        coverage_payload=coverage_payload,
        command=command,
        evidence_git_sha=_resolve_git_sha(),
        command_exit_code=max(summary_exit_code, coverage_exit_code),
    )
    if not args.reuse_existing_artifacts and not coverage_path.exists():
        snapshot["status"] = "fail"
        snapshot["warning"] = f"coverage report not found: {coverage_path}"

    output_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[INFO] wrote quality snapshot: {output_path}")

    if args.allow_fail:
        return 0
    if summary_exit_code != 0:
        return summary_exit_code
    if coverage_exit_code != 0:
        return coverage_exit_code
    if snapshot.get("status") != "pass":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
