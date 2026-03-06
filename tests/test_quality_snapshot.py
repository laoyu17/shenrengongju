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


def test_parse_pytest_summary_without_duration_suffix() -> None:
    output = """\
....................................F.................................... [100%]
1 failed, 203 passed, 2 skipped
"""
    summary = parse_pytest_summary(output)

    assert summary["passed"] == 203
    assert summary["failed"] == 1
    assert summary["skipped"] == 2
    assert summary["summary_line"] == "1 failed, 203 passed, 2 skipped"


def test_parse_pytest_summary_with_assignment_style() -> None:
    output = "pytest result: passed=361 failed=0 skipped=2"
    summary = parse_pytest_summary(output)

    assert summary["passed"] == 361
    assert summary["failed"] == 0
    assert summary["skipped"] == 2


def test_parse_pytest_summary_with_tests_keyword_style() -> None:
    output = "summary: 361 tests passed, 0 failed"
    summary = parse_pytest_summary(output)

    assert summary["passed"] == 361
    assert summary["failed"] == 0


def test_parse_pytest_summary_with_quiet_progress_only() -> None:
    output = """\
....sXxFEE [100%]
"""
    summary = parse_pytest_summary(output)

    assert summary["passed"] == 4
    assert summary["skipped"] == 1
    assert summary["xpassed"] == 1
    assert summary["xfailed"] == 1
    assert summary["failed"] == 1
    assert summary["errors"] == 2
    assert summary["parse_mode"] == "quiet_progress"


def test_parse_pytest_summary_with_ansi_quiet_progress() -> None:
    output = "\x1b[32m.....\x1b[0m [100%]\n"
    summary = parse_pytest_summary(output)

    assert summary["passed"] == 5
    assert summary["failed"] == 0
    assert summary["errors"] == 0
    assert summary["parse_mode"] == "quiet_progress"


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


def test_build_quality_snapshot_graceful_when_summary_missing() -> None:
    payload = {
        "totals": {
            "num_statements": 10,
            "covered_lines": 9,
            "missing_lines": 1,
            "percent_covered": 90.0,
            "percent_covered_display": "90",
        }
    }

    snapshot = build_quality_snapshot(
        pytest_output="",
        coverage_payload=payload,
        command="python -m pytest --cov=rtos_sim -q",
        git_sha="abc123",
        command_exit_code=1,
    )
    assert snapshot["status"] == "fail"
    assert snapshot["pytest"]["passed"] == 0
    assert "pytest summary parse failed" in str(snapshot.get("warning", ""))
