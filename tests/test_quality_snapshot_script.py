from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import subprocess
import sys

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "quality_snapshot.py"
SPEC = spec_from_file_location("quality_snapshot_script", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
quality_snapshot_script = module_from_spec(SPEC)
SPEC.loader.exec_module(quality_snapshot_script)


def _coverage_payload() -> dict:
    return {
        "totals": {
            "num_statements": 100,
            "covered_lines": 90,
            "missing_lines": 10,
            "percent_covered": 90.0,
            "percent_covered_display": "90",
        }
    }


def test_main_reuses_existing_artifacts_without_running_pytest(tmp_path: Path) -> None:
    coverage_path = tmp_path / "coverage.json"
    coverage_path.write_text(json.dumps(_coverage_payload()), encoding="utf-8")
    pytest_output_path = tmp_path / "pytest-output.txt"
    pytest_output_path.write_text(".................................... [100%]\n90 passed in 2.10s\n", encoding="utf-8")
    output_path = tmp_path / "quality-snapshot.json"

    code = quality_snapshot_script.main(
        [
            "--output",
            str(output_path),
            "--coverage-json",
            str(coverage_path),
            "--pytest-output-file",
            str(pytest_output_path),
            "--reuse-existing-artifacts",
        ]
    )

    assert code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["pytest"]["passed"] == 90
    assert payload["coverage"]["line_rate"] == 90.0
    assert payload["status"] == "pass"
    assert "reuse_existing_artifacts" in payload["command"]


def test_main_reuse_mode_requires_pytest_output_file(tmp_path: Path) -> None:
    coverage_path = tmp_path / "coverage.json"
    coverage_path.write_text(json.dumps(_coverage_payload()), encoding="utf-8")

    with pytest.raises(ValueError, match="--pytest-output-file is required"):
        quality_snapshot_script.main(
            [
                "--coverage-json",
                str(coverage_path),
                "--reuse-existing-artifacts",
            ]
        )


def test_main_reuse_mode_returns_non_zero_when_summary_has_failures(tmp_path: Path) -> None:
    coverage_path = tmp_path / "coverage.json"
    coverage_path.write_text(json.dumps(_coverage_payload()), encoding="utf-8")
    pytest_output_path = tmp_path / "pytest-output.txt"
    pytest_output_path.write_text(
        "=================== 1 failed, 9 passed in 1.00s ===================\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "quality-snapshot.json"

    code = quality_snapshot_script.main(
        [
            "--output",
            str(output_path),
            "--coverage-json",
            str(coverage_path),
            "--pytest-output-file",
            str(pytest_output_path),
            "--reuse-existing-artifacts",
        ]
    )

    assert code == 1
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "fail"
    assert payload["command_exit_code"] == 0


def test_cli_entrypoint_works_without_site_packages() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-S", str(MODULE_PATH), "--help"],
        check=False,
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    assert result.returncode == 0, result.stderr
    assert "Generate pytest+coverage quality snapshot JSON" in result.stdout
