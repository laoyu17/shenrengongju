"""Utilities for generating machine-readable quality snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

_SUMMARY_TOKENS = {"passed", "failed", "error", "errors", "skipped", "xfailed", "xpassed"}
_SUMMARY_PATTERN = re.compile(
    r"(?<![=\w])(\d+)\s+(passed|failed|error|errors|skipped|xfailed|xpassed)\b(?!\s*=)",
    re.IGNORECASE,
)
_SUMMARY_ASSIGNMENT_PATTERN = re.compile(
    r"\b(passed|failed|error|errors|skipped|xfailed|xpassed)\s*[:=]\s*(\d+)\b",
    re.IGNORECASE,
)
_SUMMARY_TOKEN_FIRST_PATTERN = re.compile(
    r"\b(passed|failed|error|errors|skipped|xfailed|xpassed)\s+(\d+)\b",
    re.IGNORECASE,
)
_SUMMARY_TESTS_PATTERN = re.compile(
    r"\b(\d+)\s+tests?\s+(passed|failed|error|errors|skipped|xfailed|xpassed)\b",
    re.IGNORECASE,
)
_QUIET_PROGRESS_PATTERN = re.compile(r"^([.FEsxX]+)\s*\[\s*\d+%\s*\]$")
_ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*m")


def _extract_counts(text: str) -> dict[str, int]:
    counts = {
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "xfailed": 0,
        "xpassed": 0,
    }
    found = False

    for count_raw, token_raw in _SUMMARY_PATTERN.findall(text):
        token = token_raw.lower()
        key = "errors" if token in {"error", "errors"} else token
        counts[key] += int(count_raw)
        found = True

    for token_raw, count_raw in _SUMMARY_ASSIGNMENT_PATTERN.findall(text):
        token = token_raw.lower()
        key = "errors" if token in {"error", "errors"} else token
        counts[key] += int(count_raw)
        found = True

    for token_raw, count_raw in _SUMMARY_TOKEN_FIRST_PATTERN.findall(text):
        token = token_raw.lower()
        key = "errors" if token in {"error", "errors"} else token
        counts[key] += int(count_raw)
        found = True

    for count_raw, token_raw in _SUMMARY_TESTS_PATTERN.findall(text):
        token = token_raw.lower()
        key = "errors" if token in {"error", "errors"} else token
        counts[key] += int(count_raw)
        found = True

    if not found:
        return {}
    return counts


def _extract_quiet_progress_counts(output: str) -> dict[str, int]:
    counts = {
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "xfailed": 0,
        "xpassed": 0,
    }
    found = False

    for raw_line in output.splitlines():
        normalized_line = _ANSI_ESCAPE_PATTERN.sub("", raw_line).strip()
        match = _QUIET_PROGRESS_PATTERN.match(normalized_line)
        if match is None:
            continue
        found = True
        for token in match.group(1):
            if token == ".":
                counts["passed"] += 1
            elif token == "F":
                counts["failed"] += 1
            elif token == "E":
                counts["errors"] += 1
            elif token == "s":
                counts["skipped"] += 1
            elif token == "x":
                counts["xfailed"] += 1
            elif token == "X":
                counts["xpassed"] += 1

    if not found:
        return {}
    return counts


def parse_pytest_summary(output: str) -> dict[str, Any]:
    """Parse the terminal pytest summary line into normalized counters."""

    summary_line: str | None = None
    fallback_line: str | None = None
    for raw_line in reversed(output.splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        counts = _extract_counts(line)
        if not counts:
            continue
        # Prefer canonical summary lines with duration suffix.
        if " in " in line:
            summary_line = line
            fallback_line = None
            break
        if fallback_line is None:
            fallback_line = line

    if summary_line is None:
        summary_line = fallback_line

    if summary_line is None:
        aggregated_counts = _extract_counts(output)
        if aggregated_counts:
            return {**aggregated_counts, "summary_line": "", "parse_mode": "aggregate_counts"}
        quiet_progress_counts = _extract_quiet_progress_counts(output)
        if quiet_progress_counts:
            return {**quiet_progress_counts, "summary_line": "", "parse_mode": "quiet_progress"}
        raise ValueError("unable to find pytest summary line")

    counts = _extract_counts(summary_line)
    if not counts:
        raise ValueError("unable to parse pytest summary counters")

    return {**counts, "summary_line": summary_line, "parse_mode": "summary_line"}


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

    pytest_parse_error: str | None = None
    try:
        pytest_summary = parse_pytest_summary(pytest_output)
    except ValueError as exc:
        pytest_parse_error = str(exc)
        pytest_summary = {
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "xfailed": 0,
            "xpassed": 0,
            "summary_line": "",
        }
    coverage_summary = summarize_coverage_payload(coverage_payload)

    status = "pass"
    if (
        pytest_parse_error is not None
        or pytest_summary["failed"] > 0
        or pytest_summary["errors"] > 0
        or command_exit_code != 0
    ):
        status = "fail"

    snapshot = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": status,
        "git_sha": git_sha,
        "command": command,
        "command_exit_code": command_exit_code,
        "pytest": pytest_summary,
        "coverage": coverage_summary,
    }
    if pytest_parse_error is not None:
        snapshot["warning"] = f"pytest summary parse failed: {pytest_parse_error}"
    return snapshot
