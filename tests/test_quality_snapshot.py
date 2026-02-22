from __future__ import annotations

import pytest

from rtos_sim.analysis.quality_snapshot import (
    build_quality_snapshot,
    parse_pytest_summary,
    summarize_coverage_payload,
)


def test_parse_pytest_summary_success_case() -> None:
    output = """\
........................................................................ [100%]
204 passed in 2.73s
"""
    summary = parse_pytest_summary(output)

    assert summary["passed"] == 204
    assert summary["failed"] == 0
    assert summary["errors"] == 0
    assert summary["summary_line"] == "204 passed in 2.73s"


def test_parse_pytest_summary_failure_case() -> None:
    output = """\
....................................F.................................... [100%]
1 failed, 203 passed, 2 skipped in 4.10s
"""
    summary = parse_pytest_summary(output)

    assert summary["passed"] == 203
    assert summary["failed"] == 1
    assert summary["skipped"] == 2


def test_parse_pytest_summary_raises_when_missing() -> None:
    with pytest.raises(ValueError, match="pytest summary line"):
        parse_pytest_summary("no summary")


def test_summarize_coverage_payload() -> None:
    coverage = summarize_coverage_payload(
        {
            "totals": {
                "num_statements": 100,
                "covered_lines": 87,
                "missing_lines": 13,
                "percent_covered": 87.0,
                "percent_covered_display": "87",
            }
        }
    )

    assert coverage["num_statements"] == 100
    assert coverage["covered_lines"] == 87
    assert coverage["line_rate"] == 87.0
    assert coverage["line_rate_display"] == "87"


def test_build_quality_snapshot_status_pass_and_fail() -> None:
    payload = {
        "totals": {
            "num_statements": 10,
            "covered_lines": 9,
            "missing_lines": 1,
            "percent_covered": 90.0,
            "percent_covered_display": "90",
        }
    }

    pass_snapshot = build_quality_snapshot(
        pytest_output="10 passed in 0.20s",
        coverage_payload=payload,
        command="python -m pytest --cov=rtos_sim -q",
        git_sha="abc123",
        command_exit_code=0,
    )
    assert pass_snapshot["status"] == "pass"

    fail_snapshot = build_quality_snapshot(
        pytest_output="1 failed, 9 passed in 0.20s",
        coverage_payload=payload,
        command="python -m pytest --cov=rtos_sim -q",
        git_sha="abc123",
        command_exit_code=1,
    )
    assert fail_snapshot["status"] == "fail"
