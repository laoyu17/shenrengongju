"""Utilities for generating machine-readable quality snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

_SUMMARY_TOKENS = {"passed", "failed", "error", "errors", "skipped", "xfailed", "xpassed"}
_SUMMARY_PATTERN = re.compile(r"(\d+)\s+(passed|failed|error|errors|skipped|xfailed|xpassed)")


def parse_pytest_summary(output: str) -> dict[str, Any]:
    """Parse the terminal pytest summary line into normalized counters."""

    summary_line: str | None = None
    for raw_line in reversed(output.splitlines()):
        line = raw_line.strip()
        if not line or " in " not in line:
            continue
        if any(f" {token}" in line for token in _SUMMARY_TOKENS):
            summary_line = line
            break

    if summary_line is None:
        raise ValueError("unable to find pytest summary line")

    counts = {
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "xfailed": 0,
        "xpassed": 0,
    }
    for count_raw, token in _SUMMARY_PATTERN.findall(summary_line):
        key = "errors" if token in {"error", "errors"} else token
        counts[key] += int(count_raw)

    return {**counts, "summary_line": summary_line}


def summarize_coverage_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize pytest-cov JSON payload into stable fields."""

    totals = payload.get("totals")
    if not isinstance(totals, dict):
        raise ValueError("coverage payload missing totals")

    num_statements = int(totals.get("num_statements", 0))
    covered_lines = int(totals.get("covered_lines", 0))
    missing_lines = int(totals.get("missing_lines", max(num_statements - covered_lines, 0)))
    percent = float(
        totals.get(
            "percent_covered",
            (covered_lines * 100.0 / num_statements) if num_statements else 100.0,
        )
    )

    return {
        "num_statements": num_statements,
        "covered_lines": covered_lines,
        "missing_lines": missing_lines,
        "line_rate": percent,
        "line_rate_display": str(totals.get("percent_covered_display", f"{percent:.2f}")),
    }


def build_quality_snapshot(
    *,
    pytest_output: str,
    coverage_payload: dict[str, Any],
    command: str,
    git_sha: str | None,
    command_exit_code: int,
) -> dict[str, Any]:
    """Build a single quality snapshot from pytest and coverage outputs."""

    pytest_summary = parse_pytest_summary(pytest_output)
    coverage_summary = summarize_coverage_payload(coverage_payload)

    status = "pass"
    if pytest_summary["failed"] > 0 or pytest_summary["errors"] > 0 or command_exit_code != 0:
        status = "fail"

    return {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": status,
        "git_sha": git_sha,
        "command": command,
        "command_exit_code": command_exit_code,
        "pytest": pytest_summary,
        "coverage": coverage_summary,
    }
