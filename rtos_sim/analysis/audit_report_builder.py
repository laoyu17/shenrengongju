"""Internal report-building helpers for audit checks orchestration."""

from __future__ import annotations

from typing import Any, TypedDict


class CheckOutcome(TypedDict):
    """Internal check contract: one rule, one result payload, optional issues."""

    rule: str
    passed: bool
    issues: list[dict[str, Any]]
    check_payload: dict[str, Any]


def make_check_outcome(
    *,
    rule: str,
    passed: bool,
    issues: list[dict[str, Any]] | None = None,
    check_payload: dict[str, Any] | None = None,
) -> CheckOutcome:
    return {
        "rule": rule,
        "passed": bool(passed),
        "issues": list(issues or []),
        "check_payload": dict(check_payload or {}),
    }


def append_check_outcome(
    *,
    checks: dict[str, Any],
    issues: list[dict[str, Any]],
    outcome: CheckOutcome,
) -> None:
    issues.extend(outcome["issues"])
    checks[outcome["rule"]] = {
        "passed": outcome["passed"],
        **outcome["check_payload"],
    }
